#include "cth3ds/th3ds.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <charconv>
#include <cstring>
#include <fstream>
#include <functional>
#include <limits>
#include <map>
#include <set>
#include <system_error>
#include <utility>

namespace cth3ds {
namespace {

constexpr std::array<std::uint8_t, 8> kMagic{{'T', 'H', '3', 'D', 'S', 'R',
                                               '1', 0U}};
constexpr std::array<std::uint8_t, 8> kLegacyMagic{{'C', 'T', 'H', '3', 'D',
                                                     'P', 'K', '1'}};
constexpr std::uint64_t kHeaderSize = 256U;
constexpr std::uint64_t kIndexEntrySize = 128U;
constexpr std::uint64_t kDefaultAlignment = 64U;
constexpr std::uint64_t kAudioAlignment = 4096U;
constexpr std::uint64_t kMaximumResourceBytes = 64U * 1024U * 1024U;
constexpr std::uint64_t kMaximumJsonBytes = 1024U * 1024U;
constexpr std::uint32_t kKnownFlags = 7U;

ResourceError error(ResourceErrorCode code, std::string message,
                    ResourceId id = {}) {
  return {code, std::move(message), id};
}

template <typename T>
T read_le(const std::uint8_t* bytes) noexcept {
  T result = 0;
  for (std::size_t index = 0U; index < sizeof(T); ++index) {
    result |= static_cast<T>(static_cast<T>(bytes[index]) << (index * 8U));
  }
  return result;
}

bool checked_add(std::uint64_t left, std::uint64_t right,
                 std::uint64_t& result) noexcept {
  if (right > std::numeric_limits<std::uint64_t>::max() - left) {
    return false;
  }
  result = left + right;
  return true;
}

bool checked_multiply(std::uint64_t left, std::uint64_t right,
                      std::uint64_t& result) noexcept {
  if (left != 0U && right > std::numeric_limits<std::uint64_t>::max() / left) {
    return false;
  }
  result = left * right;
  return true;
}

bool valid_utf8(std::string_view value) noexcept {
  std::size_t index = 0U;
  while (index < value.size()) {
    const auto first = static_cast<std::uint8_t>(value[index]);
    if (first < 0x80U) {
      ++index;
      continue;
    }
    std::size_t length = 0U;
    std::uint32_t codepoint = 0U;
    if (first >= 0xC2U && first <= 0xDFU) {
      length = 2U;
      codepoint = first & 0x1FU;
    } else if (first >= 0xE0U && first <= 0xEFU) {
      length = 3U;
      codepoint = first & 0x0FU;
    } else if (first >= 0xF0U && first <= 0xF4U) {
      length = 4U;
      codepoint = first & 0x07U;
    } else {
      return false;
    }
    if (length > value.size() - index) {
      return false;
    }
    for (std::size_t part = 1U; part < length; ++part) {
      const auto byte = static_cast<std::uint8_t>(value[index + part]);
      if ((byte & 0xC0U) != 0x80U) {
        return false;
      }
      codepoint = (codepoint << 6U) | (byte & 0x3FU);
    }
    const bool overlong = (length == 2U && codepoint < 0x80U) ||
                          (length == 3U && codepoint < 0x800U) ||
                          (length == 4U && codepoint < 0x10000U);
    if (overlong || codepoint > 0x10FFFFU ||
        (codepoint >= 0xD800U && codepoint <= 0xDFFFU)) {
      return false;
    }
    index += length;
  }
  return true;
}

void append_utf8(std::string& output, std::uint32_t codepoint) {
  if (codepoint <= 0x7FU) {
    output.push_back(static_cast<char>(codepoint));
  } else if (codepoint <= 0x7FFU) {
    output.push_back(static_cast<char>(0xC0U | (codepoint >> 6U)));
    output.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
  } else if (codepoint <= 0xFFFFU) {
    output.push_back(static_cast<char>(0xE0U | (codepoint >> 12U)));
    output.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3FU)));
    output.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
  } else {
    output.push_back(static_cast<char>(0xF0U | (codepoint >> 18U)));
    output.push_back(static_cast<char>(0x80U | ((codepoint >> 12U) & 0x3FU)));
    output.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3FU)));
    output.push_back(static_cast<char>(0x80U | (codepoint & 0x3FU)));
  }
}

struct Json {
  enum class Type { Null, Boolean, Integer, String, Array, Object };
  Type type{Type::Null};
  bool boolean{false};
  std::int64_t integer{0};
  std::string string{};
  std::vector<Json> array{};
  std::map<std::string, Json> object{};

  [[nodiscard]] const Json* get(std::string_view key) const noexcept {
    if (type != Type::Object) return nullptr;
    const auto iterator = object.find(std::string(key));
    return iterator == object.end() ? nullptr : &iterator->second;
  }
};

class JsonParser {
 public:
  explicit JsonParser(std::string_view input) : input_(input) {}

  bool parse(Json& value, std::string& detail) {
    if (!parse_value(value, 0U) || position_ != input_.size()) {
      detail = detail_.empty() ? "JSON has trailing bytes" : detail_;
      return false;
    }
    return true;
  }

 private:
  bool parse_value(Json& value, std::size_t depth) {
    if (depth > 64U || position_ >= input_.size()) {
      return fail(depth > 64U ? "JSON nesting exceeds 64" : "truncated JSON");
    }
    const char token = input_[position_];
    if (token == '{') return parse_object(value, depth + 1U);
    if (token == '[') return parse_array(value, depth + 1U);
    if (token == '"') {
      value.type = Json::Type::String;
      return parse_string(value.string);
    }
    if (token == 't' && consume("true")) {
      value.type = Json::Type::Boolean;
      value.boolean = true;
      return true;
    }
    if (token == 'f' && consume("false")) {
      value.type = Json::Type::Boolean;
      value.boolean = false;
      return true;
    }
    if (token == 'n' && consume("null")) {
      value.type = Json::Type::Null;
      return true;
    }
    return parse_integer(value);
  }

  bool parse_object(Json& value, std::size_t depth) {
    ++position_;
    value.type = Json::Type::Object;
    if (take('}')) return true;
    while (position_ < input_.size()) {
      std::string key;
      if (!parse_string(key) || !take(':')) return false;
      Json child;
      if (!parse_value(child, depth)) return false;
      if (!value.object.emplace(std::move(key), std::move(child)).second) {
        return fail("JSON object contains a duplicate key");
      }
      if (take('}')) return true;
      if (!take(',')) return fail("JSON object separator is invalid");
    }
    return fail("truncated JSON object");
  }

  bool parse_array(Json& value, std::size_t depth) {
    ++position_;
    value.type = Json::Type::Array;
    if (take(']')) return true;
    while (position_ < input_.size()) {
      Json child;
      if (!parse_value(child, depth)) return false;
      value.array.push_back(std::move(child));
      if (take(']')) return true;
      if (!take(',')) return fail("JSON array separator is invalid");
    }
    return fail("truncated JSON array");
  }

  bool parse_integer(Json& value) {
    const std::size_t begin = position_;
    if (take('-') && position_ == input_.size()) return fail("truncated integer");
    if (position_ >= input_.size() || input_[position_] < '0' ||
        input_[position_] > '9') {
      return fail("JSON token is unsupported");
    }
    if (input_[position_] == '0') {
      ++position_;
      if (position_ < input_.size() && input_[position_] >= '0' &&
          input_[position_] <= '9') {
        return fail("JSON integer has a leading zero");
      }
    } else {
      while (position_ < input_.size() && input_[position_] >= '0' &&
             input_[position_] <= '9') {
        ++position_;
      }
    }
    if (position_ < input_.size() &&
        (input_[position_] == '.' || input_[position_] == 'e' ||
         input_[position_] == 'E')) {
      return fail("TH3DS JSON forbids floating-point values");
    }
    const std::string_view encoded = input_.substr(begin, position_ - begin);
    std::int64_t parsed = 0;
    const auto converted =
        std::from_chars(encoded.data(), encoded.data() + encoded.size(), parsed);
    if (converted.ec != std::errc{} || converted.ptr != encoded.data() + encoded.size()) {
      return fail("JSON integer is out of range");
    }
    value.type = Json::Type::Integer;
    value.integer = parsed;
    return true;
  }

  bool parse_string(std::string& value) {
    if (!take('"')) return fail("JSON string is missing a quote");
    while (position_ < input_.size()) {
      const auto byte = static_cast<std::uint8_t>(input_[position_++]);
      if (byte == '"') {
        return valid_utf8(value) || fail("JSON string is not valid UTF-8");
      }
      if (byte < 0x20U) return fail("JSON string contains a control byte");
      if (byte != '\\') {
        value.push_back(static_cast<char>(byte));
        continue;
      }
      if (position_ >= input_.size()) return fail("truncated JSON escape");
      const char escape = input_[position_++];
      switch (escape) {
        case '"': value.push_back('"'); break;
        case '\\': value.push_back('\\'); break;
        case '/': value.push_back('/'); break;
        case 'b': value.push_back('\b'); break;
        case 'f': value.push_back('\f'); break;
        case 'n': value.push_back('\n'); break;
        case 'r': value.push_back('\r'); break;
        case 't': value.push_back('\t'); break;
        case 'u': {
          std::uint32_t codepoint = 0U;
          if (!parse_hex4(codepoint)) return false;
          if (codepoint >= 0xD800U && codepoint <= 0xDBFFU) {
            if (!consume("\\u")) return fail("JSON high surrogate has no pair");
            std::uint32_t low = 0U;
            if (!parse_hex4(low) || low < 0xDC00U || low > 0xDFFFU) {
              return fail("JSON surrogate pair is invalid");
            }
            codepoint = 0x10000U + ((codepoint - 0xD800U) << 10U) +
                        (low - 0xDC00U);
          } else if (codepoint >= 0xDC00U && codepoint <= 0xDFFFU) {
            return fail("JSON low surrogate has no pair");
          }
          append_utf8(value, codepoint);
          break;
        }
        default: return fail("JSON escape is invalid");
      }
    }
    return fail("truncated JSON string");
  }

  bool parse_hex4(std::uint32_t& result) {
    if (input_.size() - position_ < 4U) return fail("truncated Unicode escape");
    result = 0U;
    for (std::size_t index = 0U; index < 4U; ++index) {
      const char value = input_[position_++];
      const int digit = value >= '0' && value <= '9'
                            ? value - '0'
                            : (value >= 'a' && value <= 'f'
                                   ? value - 'a' + 10
                                   : (value >= 'A' && value <= 'F'
                                          ? value - 'A' + 10
                                          : -1));
      if (digit < 0) return fail("Unicode escape is invalid");
      result = (result << 4U) | static_cast<std::uint32_t>(digit);
    }
    return true;
  }

  bool consume(std::string_view token) {
    if (input_.substr(position_, token.size()) != token) return false;
    position_ += token.size();
    return true;
  }

  bool take(char token) {
    if (position_ >= input_.size() || input_[position_] != token) return false;
    ++position_;
    return true;
  }

  bool fail(const char* detail) {
    if (detail_.empty()) detail_ = detail;
    return false;
  }

  std::string_view input_;
  std::size_t position_{0U};
  std::string detail_{};
};

void encode_json_string(const std::string& value, std::string& output) {
  constexpr char digits[] = "0123456789abcdef";
  output.push_back('"');
  for (const char character : value) {
    const auto byte = static_cast<unsigned char>(character);
    switch (byte) {
      case '"': output += "\\\""; break;
      case '\\': output += "\\\\"; break;
      case '\b': output += "\\b"; break;
      case '\f': output += "\\f"; break;
      case '\n': output += "\\n"; break;
      case '\r': output += "\\r"; break;
      case '\t': output += "\\t"; break;
      default:
        if (byte < 0x20U) {
          output += "\\u00";
          output.push_back(digits[byte >> 4U]);
          output.push_back(digits[byte & 0x0FU]);
        } else {
          output.push_back(static_cast<char>(byte));
        }
    }
  }
  output.push_back('"');
}

void encode_json(const Json& value, std::string& output) {
  switch (value.type) {
    case Json::Type::Null: output += "null"; return;
    case Json::Type::Boolean: output += value.boolean ? "true" : "false"; return;
    case Json::Type::Integer: output += std::to_string(value.integer); return;
    case Json::Type::String: encode_json_string(value.string, output); return;
    case Json::Type::Array:
      output.push_back('[');
      for (std::size_t index = 0U; index < value.array.size(); ++index) {
        if (index != 0U) output.push_back(',');
        encode_json(value.array[index], output);
      }
      output.push_back(']');
      return;
    case Json::Type::Object:
      output.push_back('{');
      for (auto iterator = value.object.begin(); iterator != value.object.end();
           ++iterator) {
        if (iterator != value.object.begin()) output.push_back(',');
        encode_json_string(iterator->first, output);
        output.push_back(':');
        encode_json(iterator->second, output);
      }
      output.push_back('}');
      return;
  }
}

ResourceResult<Json> parse_canonical_json(ByteView bytes, const char* label) {
  if (bytes.size == 0U || bytes.size > kMaximumJsonBytes || bytes.data == nullptr) {
    return ResourceResult<Json>::failure(error(
        ResourceErrorCode::FormatCanonicalJson,
        std::string(label) + " JSON size is invalid"));
  }
  const std::string_view input(reinterpret_cast<const char*>(bytes.data), bytes.size);
  Json value;
  std::string detail;
  JsonParser parser(input);
  if (!parser.parse(value, detail)) {
    return ResourceResult<Json>::failure(error(
        ResourceErrorCode::FormatCanonicalJson,
        std::string(label) + " is invalid: " + detail));
  }
  std::string canonical;
  canonical.reserve(bytes.size);
  encode_json(value, canonical);
  if (canonical != input) {
    return ResourceResult<Json>::failure(error(
        ResourceErrorCode::FormatCanonicalJson,
        std::string(label) + " is not canonical JSON"));
  }
  return ResourceResult<Json>::success(std::move(value));
}

const std::string* json_string(const Json* value) noexcept {
  return value != nullptr && value->type == Json::Type::String ? &value->string
                                                               : nullptr;
}

std::optional<std::uint64_t> json_unsigned(const Json* value) noexcept {
  if (value == nullptr || value->type != Json::Type::Integer || value->integer < 0) {
    return std::nullopt;
  }
  return static_cast<std::uint64_t>(value->integer);
}

bool json_null(const Json* value) noexcept {
  return value != nullptr && value->type == Json::Type::Null;
}

std::optional<bool> json_boolean(const Json* value) noexcept {
  if (value == nullptr || value->type != Json::Type::Boolean) {
    return std::nullopt;
  }
  return value->boolean;
}

bool json_version(const Json* value,
                  std::optional<std::uint16_t> expected_minor = {}) noexcept {
  const auto minor = value == nullptr ? std::nullopt
                                      : json_unsigned(value->get("minor"));
  return value != nullptr && value->type == Json::Type::Object &&
         json_unsigned(value->get("major")) == 1U && minor.has_value() &&
         *minor <= std::numeric_limits<std::uint16_t>::max() &&
         (!expected_minor || *minor == *expected_minor);
}

ResourceResult<std::vector<std::uint8_t>> read_file_range(
    const std::filesystem::path& path, std::uint64_t offset, std::uint64_t size,
    std::uint64_t maximum, const char* label) {
  if (size > maximum || size > static_cast<std::uint64_t>(
                                 std::numeric_limits<std::size_t>::max()) ||
      offset > static_cast<std::uint64_t>(
                   std::numeric_limits<std::streamoff>::max())) {
    return ResourceResult<std::vector<std::uint8_t>>::failure(
        error(ResourceErrorCode::FormatBounds,
              std::string(label) + " range exceeds runtime limits"));
  }
  std::vector<std::uint8_t> data;
  try {
    data.resize(static_cast<std::size_t>(size));
  } catch (const std::bad_alloc&) {
    return ResourceResult<std::vector<std::uint8_t>>::failure(
        error(ResourceErrorCode::AllocationFailed,
              std::string(label) + " allocation failed"));
  }
  std::ifstream stream(path, std::ios::binary);
  if (!stream) {
    return ResourceResult<std::vector<std::uint8_t>>::failure(
        error(ResourceErrorCode::Io, "cannot open " + path.string()));
  }
  stream.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
  if (!stream || size > static_cast<std::uint64_t>(
                            std::numeric_limits<std::streamsize>::max())) {
    return ResourceResult<std::vector<std::uint8_t>>::failure(
        error(ResourceErrorCode::Io, "cannot seek " + path.string()));
  }
  if (size != 0U) {
    stream.read(reinterpret_cast<char*>(data.data()),
                static_cast<std::streamsize>(size));
  }
  if (!stream || static_cast<std::uint64_t>(stream.gcount()) != size) {
    return ResourceResult<std::vector<std::uint8_t>>::failure(
        error(ResourceErrorCode::Io, "truncated read from " + path.string()));
  }
  return ResourceResult<std::vector<std::uint8_t>>::success(std::move(data));
}

ResourceResult<std::uint64_t> runtime_file_size(const std::filesystem::path& path) {
  std::error_code system_error;
  const auto size = std::filesystem::file_size(path, system_error);
  if (system_error) {
    return ResourceResult<std::uint64_t>::failure(
        error(ResourceErrorCode::Io, "cannot stat " + path.string()));
  }
  return ResourceResult<std::uint64_t>::success(size);
}

ResourceResult<Sha256Digest> hash_file(const std::filesystem::path& path,
                                       std::uint64_t offset,
                                       std::uint64_t size,
                                       bool zero_container_field = false) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream || offset > static_cast<std::uint64_t>(
                             std::numeric_limits<std::streamoff>::max())) {
    return ResourceResult<Sha256Digest>::failure(
        error(ResourceErrorCode::Io, "cannot hash " + path.string()));
  }
  stream.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
  std::array<std::uint8_t, 64U * 1024U> buffer{};
  Sha256 hash;
  std::uint64_t consumed = 0U;
  while (consumed < size) {
    const std::uint64_t remaining = size - consumed;
    const std::size_t request = static_cast<std::size_t>(
        std::min<std::uint64_t>(remaining, buffer.size()));
    stream.read(reinterpret_cast<char*>(buffer.data()),
                static_cast<std::streamsize>(request));
    if (!stream || stream.gcount() != static_cast<std::streamsize>(request)) {
      return ResourceResult<Sha256Digest>::failure(
          error(ResourceErrorCode::Io, "truncated hash read from " + path.string()));
    }
    if (zero_container_field) {
      const std::uint64_t chunk_begin = offset + consumed;
      const std::uint64_t chunk_end = chunk_begin + request;
      const std::uint64_t zero_begin = std::max<std::uint64_t>(chunk_begin, 0xA8U);
      const std::uint64_t zero_end = std::min<std::uint64_t>(chunk_end, 0xC8U);
      if (zero_begin < zero_end) {
        std::fill(buffer.begin() + static_cast<std::ptrdiff_t>(zero_begin - chunk_begin),
                  buffer.begin() + static_cast<std::ptrdiff_t>(zero_end - chunk_begin),
                  0U);
      }
    }
    hash.update(buffer.data(), request);
    consumed += request;
  }
  return ResourceResult<Sha256Digest>::success(hash.finish());
}

ResourceResult<void> require_zero_range(const std::filesystem::path& path,
                                        std::uint64_t offset,
                                        std::uint64_t size,
                                        const char* label) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream || offset > static_cast<std::uint64_t>(
                             std::numeric_limits<std::streamoff>::max())) {
    return ResourceResult<void>::failure(
        error(ResourceErrorCode::Io, "cannot inspect padding in " + path.string()));
  }
  stream.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
  std::array<std::uint8_t, 4096> buffer{};
  std::uint64_t consumed = 0U;
  while (consumed < size) {
    const std::size_t request = static_cast<std::size_t>(
        std::min<std::uint64_t>(size - consumed, buffer.size()));
    stream.read(reinterpret_cast<char*>(buffer.data()),
                static_cast<std::streamsize>(request));
    if (!stream || stream.gcount() != static_cast<std::streamsize>(request)) {
      return ResourceResult<void>::failure(
          error(ResourceErrorCode::Io, "truncated padding in " + path.string()));
    }
    if (std::any_of(buffer.begin(),
                    buffer.begin() + static_cast<std::ptrdiff_t>(request),
                    [](std::uint8_t value) { return value != 0U; })) {
      return ResourceResult<void>::failure(
          error(ResourceErrorCode::FormatBounds,
                std::string("non-zero padding before ") + label));
    }
    consumed += request;
  }
  return ResourceResult<void>::success();
}

PackageId package_id(PackageRole role, const std::string& name,
                     const Sha256Digest& source) {
  Sha256 hash;
  constexpr char prefix[] = "th3ds-package-id-v1";
  hash.update(prefix, sizeof(prefix));
  const char* role_name = role == PackageRole::Core
                              ? "core"
                              : (role == PackageRole::Language ? "language" : "level");
  hash.update(role_name, std::strlen(role_name));
  const std::uint8_t zero = 0U;
  hash.update(&zero, 1U);
  hash.update(name.data(), name.size());
  hash.update(&zero, 1U);
  hash.update(source.data(), source.size());
  const std::array<std::uint8_t, 4> abi{{1U, 0U, 0U, 0U}};
  hash.update(abi.data(), abi.size());
  const Sha256Digest digest = hash.finish();
  PackageId result{};
  std::copy_n(digest.begin(), result.size(), result.begin());
  return result;
}

bool parse_hex16(const std::string& value, PackageId& result) noexcept {
  ResourceId id{};
  if (!parse_resource_id_hex(value, id)) return false;
  std::copy(id.begin(), id.end(), result.begin());
  return true;
}

const char* role_name(PackageRole role) noexcept {
  switch (role) {
    case PackageRole::Core: return "core";
    case PackageRole::Language: return "language";
    case PackageRole::Level: return "level";
  }
  return "unknown";
}

std::optional<PackageRole> parse_role(std::uint32_t value) noexcept {
  if (value == 1U) return PackageRole::Core;
  if (value == 2U) return PackageRole::Language;
  if (value == 3U) return PackageRole::Level;
  return std::nullopt;
}

std::optional<ResourceKind> parse_kind(std::uint16_t value) noexcept {
  switch (value) {
    case 1U: return ResourceKind::AudioBank;
    case 2U: return ResourceKind::LanguageBundle;
    case 3U: return ResourceKind::SpriteSheet;
    case 4U: return ResourceKind::UiBitmap;
    case 5U: return ResourceKind::FontAtlas;
    case 6U: return ResourceKind::FontMap;
    case 7U: return ResourceKind::Palette;
    case 255U: return ResourceKind::OpaqueBlob;
    default: return std::nullopt;
  }
}

struct PackageDeclaration {
  std::string path;
  PackageRole role;
  PackageId id{};
  Sha256Digest container{};
  std::uint64_t size{0U};
};

bool safe_bundle_path(const std::string& value) noexcept {
  if (value.empty() || value.front() == '/' || value.back() == '/' ||
      value.find("//") != std::string::npos) {
    return false;
  }
  std::size_t begin = 0U;
  while (begin < value.size()) {
    const std::size_t end = value.find('/', begin);
    const std::string_view part(
        value.data() + begin,
        (end == std::string::npos ? value.size() : end) - begin);
    if (part.empty() || part == "." || part == "..") return false;
    for (const char byte : part) {
      if (!((byte >= 'a' && byte <= 'z') || (byte >= '0' && byte <= '9') ||
            byte == '.' || byte == '_' || byte == '-')) {
        return false;
      }
    }
    if (end == std::string::npos) break;
    begin = end + 1U;
  }
  return true;
}

bool canonical_package_path(const std::string& path, PackageRole role) noexcept {
  if (role == PackageRole::Core) return path == "core.th3ds";
  const std::string_view prefix = role == PackageRole::Language ? "lang/" : "level/";
  if (path.size() <= prefix.size() + 6U ||
      std::string_view(path).substr(0U, prefix.size()) != prefix ||
      std::string_view(path).substr(path.size() - 6U) != ".th3ds") {
    return false;
  }
  return path.find('/', prefix.size()) == std::string::npos;
}

bool kind_allowed_in_role(PackageRole role, ResourceKind kind) noexcept {
  if (role == PackageRole::Language) {
    return kind == ResourceKind::LanguageBundle || kind == ResourceKind::FontAtlas ||
           kind == ResourceKind::FontMap;
  }
  if (role == PackageRole::Level) {
    return kind == ResourceKind::AudioBank || kind == ResourceKind::SpriteSheet ||
           kind == ResourceKind::UiBitmap || kind == ResourceKind::Palette ||
           kind == ResourceKind::OpaqueBlob;
  }
  return kind != ResourceKind::LanguageBundle && kind != ResourceKind::FontMap &&
         kind != ResourceKind::FontAtlas;
}

bool dependency_kind_allowed(ResourceKind source, ResourceKind target) noexcept {
  switch (source) {
    case ResourceKind::FontMap: return target == ResourceKind::FontAtlas;
    case ResourceKind::SpriteSheet:
    case ResourceKind::UiBitmap: return target == ResourceKind::Palette;
    case ResourceKind::OpaqueBlob: return target == ResourceKind::OpaqueBlob;
    case ResourceKind::AudioBank:
    case ResourceKind::LanguageBundle:
    case ResourceKind::FontAtlas:
    case ResourceKind::Palette: return false;
  }
  return false;
}

bool resource_contract_allowed(const ResourceDescriptor& descriptor,
                               PackageRole role) noexcept {
  if (!kind_allowed_in_role(role, descriptor.kind) || descriptor.group_id == 0U) {
    return false;
  }
  const bool streamable = descriptor.streamable();
  if ((descriptor.kind == ResourceKind::AudioBank ||
       descriptor.kind == ResourceKind::SpriteSheet) != streamable) {
    return false;
  }
  if (descriptor.kind == ResourceKind::AudioBank) {
    return descriptor.alignment == kAudioAlignment && !descriptor.pin_on_mount();
  }
  if (descriptor.alignment != kDefaultAlignment) return false;
  if (descriptor.pin_on_mount()) {
    return descriptor.kind == ResourceKind::UiBitmap ||
           descriptor.kind == ResourceKind::LanguageBundle ||
           descriptor.kind == ResourceKind::FontAtlas ||
           descriptor.kind == ResourceKind::FontMap;
  }
  return true;
}

bool resource_metadata_allowed(const ResourceDescriptor& descriptor,
                               const Json& metadata) noexcept {
  if (metadata.type != Json::Type::Object) return false;
  const std::string* pool = json_string(metadata.get("cache_pool"));
  const std::string* payload = json_string(metadata.get("payload_format"));
  switch (descriptor.kind) {
    case ResourceKind::AudioBank:
      return pool != nullptr && *pool == "audio" && payload != nullptr &&
             *payload == "TH3DSND1" &&
             json_unsigned(metadata.get("entry_count")).has_value();
    case ResourceKind::SpriteSheet:
      return pool != nullptr && *pool == "sprite" && payload != nullptr &&
             *payload == "TH3DSP1" &&
             json_unsigned(metadata.get("sprite_count")).has_value();
    case ResourceKind::LanguageBundle:
      return pool != nullptr && *pool == "language_font" && payload != nullptr &&
             *payload == "TH3DSLG1" && json_string(metadata.get("tag")) != nullptr;
    case ResourceKind::UiBitmap:
    case ResourceKind::FontAtlas:
      return json_unsigned(metadata.get("width")).value_or(0U) != 0U &&
             json_unsigned(metadata.get("height")).value_or(0U) != 0U &&
             json_string(metadata.get("pixel_format")) != nullptr;
    case ResourceKind::FontMap: {
      ResourceId atlas{};
      const std::string* atlas_id = json_string(metadata.get("atlas_resource_id"));
      const std::string* encoding = json_string(metadata.get("encoding"));
      return atlas_id != nullptr && parse_resource_id_hex(*atlas_id, atlas) &&
             encoding != nullptr && *encoding == "canonical-json-v1" &&
             descriptor.dependencies.size() == 1U &&
             descriptor.dependencies.front() == atlas;
    }
    case ResourceKind::Palette:
    case ResourceKind::OpaqueBlob: return true;
  }
  return false;
}

ResourceResult<std::filesystem::path> safe_package_file(
    const std::filesystem::path& root, const std::string& relative) {
  std::filesystem::path current = root;
  std::error_code system_error;
  for (const std::filesystem::path& part : std::filesystem::path(relative)) {
    current /= part;
    const auto status = std::filesystem::symlink_status(current, system_error);
    if (system_error) {
      if (system_error == std::errc::no_such_file_or_directory) {
        return ResourceResult<std::filesystem::path>::failure(error(
            ResourceErrorCode::PackageMissing,
            "bundle package path is missing: " + relative));
      }
      return ResourceResult<std::filesystem::path>::failure(error(
          ResourceErrorCode::Io,
          "cannot inspect bundle package path: " + relative));
    }
    if (std::filesystem::is_symlink(status)) {
      return ResourceResult<std::filesystem::path>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "bundle package path contains a symlink: " + relative));
    }
  }
  if (!std::filesystem::is_regular_file(current, system_error) || system_error) {
    return ResourceResult<std::filesystem::path>::failure(error(
        ResourceErrorCode::PackageMissing,
        "bundle package is not a regular file: " + relative));
  }
  return ResourceResult<std::filesystem::path>::success(std::move(current));
}

ResourceErrorCode budget_error(ResourcePool pool) noexcept {
  switch (pool) {
    case ResourcePool::Audio: return ResourceErrorCode::BudgetAudio;
    case ResourcePool::Sprite: return ResourceErrorCode::BudgetSprite;
    case ResourcePool::Texture: return ResourceErrorCode::BudgetTexture;
    case ResourcePool::LanguageFont: return ResourceErrorCode::BudgetLanguageFont;
    case ResourcePool::Metadata: return ResourceErrorCode::BudgetMetadata;
    case ResourcePool::Scratch: return ResourceErrorCode::BudgetScratch;
    case ResourcePool::Unclassified:
    case ResourcePool::Count: return ResourceErrorCode::BudgetContract;
  }
  return ResourceErrorCode::BudgetContract;
}

ResourceResult<MountedPackage> mount_package(
    const std::filesystem::path& path, const PackageDeclaration& declaration,
    const Sha256Digest& family_source) {
  const auto size_result = runtime_file_size(path);
  if (!size_result) return ResourceResult<MountedPackage>::failure(size_result.error());
  const std::uint64_t size = size_result.value();
  if (size != declaration.size || size < kHeaderSize) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::PackageMismatch,
        "package size differs from bundle declaration: " + declaration.path));
  }
  auto header_result = read_file_range(path, 0U, kHeaderSize, kHeaderSize, "header");
  if (!header_result) {
    return ResourceResult<MountedPackage>::failure(header_result.error());
  }
  const auto& header = header_result.value();
  if (std::equal(kLegacyMagic.begin(), kLegacyMagic.end(), header.begin())) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::LegacyAuditPack,
        "CTH3DPK1 is an audit archive and cannot be runtime-mounted"));
  }
  if (!std::equal(kMagic.begin(), kMagic.end(), header.begin())) {
    return ResourceResult<MountedPackage>::failure(
        error(ResourceErrorCode::FormatMagic, "TH3DSR1 magic is missing"));
  }
  const std::uint16_t header_size = read_le<std::uint16_t>(&header[0x08]);
  const std::uint16_t major = read_le<std::uint16_t>(&header[0x0A]);
  const std::uint16_t minor = read_le<std::uint16_t>(&header[0x0C]);
  const std::uint16_t header_flags = read_le<std::uint16_t>(&header[0x0E]);
  if (major != 1U) {
    return ResourceResult<MountedPackage>::failure(
        error(ResourceErrorCode::FormatMajor, "unsupported TH3DS major version"));
  }
  if (header_size != kHeaderSize) {
    return ResourceResult<MountedPackage>::failure(
        error(ResourceErrorCode::FormatBounds, "TH3DS header size is not 256"));
  }
  const std::uint32_t endian = read_le<std::uint32_t>(&header[0x10]);
  const std::uint32_t alignment = read_le<std::uint32_t>(&header[0x14]);
  const auto package_role = parse_role(read_le<std::uint32_t>(&header[0x18]));
  const std::uint32_t entry_size = read_le<std::uint32_t>(&header[0x1C]);
  const std::uint64_t manifest_offset = read_le<std::uint64_t>(&header[0x20]);
  const std::uint64_t manifest_size = read_le<std::uint64_t>(&header[0x28]);
  const std::uint64_t index_offset = read_le<std::uint64_t>(&header[0x30]);
  const std::uint32_t index_count = read_le<std::uint32_t>(&header[0x38]);
  const std::uint32_t reserved_0 = read_le<std::uint32_t>(&header[0x3C]);
  const std::uint64_t metadata_offset = read_le<std::uint64_t>(&header[0x40]);
  const std::uint64_t metadata_size = read_le<std::uint64_t>(&header[0x48]);
  const std::uint64_t data_offset = read_le<std::uint64_t>(&header[0x50]);
  const std::uint64_t data_size = read_le<std::uint64_t>(&header[0x58]);
  const std::uint64_t build_epoch = read_le<std::uint64_t>(&header[0x60]);
  const std::uint32_t required_abi = read_le<std::uint32_t>(&header[0xE8]);
  const std::uint32_t feature_bits = read_le<std::uint32_t>(&header[0xEC]);
  if (header_flags != 0U || reserved_0 != 0U || build_epoch != 0U ||
      std::any_of(header.begin() + 0xF0, header.end(),
                  [](std::uint8_t byte) { return byte != 0U; })) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::HeaderReserved,
        "TH3DS header contains a non-zero reserved field"));
  }
  if (endian != 0x01020304U || alignment != kDefaultAlignment ||
      entry_size != kIndexEntrySize || !package_role ||
      *package_role != declaration.role || index_count == 0U ||
      index_count > 65535U) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::UnsupportedFeature,
        "TH3DS endian, alignment, role or index contract is unsupported"));
  }
  if (required_abi != kTh3dsRuntimeAbi) {
    return ResourceResult<MountedPackage>::failure(
        error(ResourceErrorCode::RuntimeAbi, "TH3DS runtime ABI is unsupported"));
  }
  if (feature_bits != 0U) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::UnsupportedFeature,
        "TH3DS package requires unknown feature bits"));
  }

  std::uint64_t index_bytes = 0U;
  if (!checked_multiply(index_count, kIndexEntrySize, index_bytes)) {
    return ResourceResult<MountedPackage>::failure(
        error(ResourceErrorCode::FormatBounds, "TH3DS index size overflow"));
  }
  struct Region {
    std::uint64_t offset;
    std::uint64_t size;
    const char* name;
  };
  const std::array<Region, 4> regions{{
      {manifest_offset, manifest_size, "manifest"},
      {index_offset, index_bytes, "index"},
      {metadata_offset, metadata_size, "metadata"},
      {data_offset, data_size, "data"},
  }};
  std::uint64_t previous_end = kHeaderSize;
  for (const Region& region : regions) {
    std::uint64_t end = 0U;
    if (region.offset % kDefaultAlignment != 0U ||
        region.offset < previous_end || !checked_add(region.offset, region.size, end) ||
        end > size) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::FormatBounds,
          std::string("TH3DS ") + region.name +
              " region is overlapping, unaligned or out of bounds"));
    }
    const auto padding =
        require_zero_range(path, previous_end, region.offset - previous_end, region.name);
    if (!padding) return ResourceResult<MountedPackage>::failure(padding.error());
    previous_end = end;
  }
  if (previous_end != size || manifest_size > kMaximumJsonBytes ||
      metadata_size > kMaximumJsonBytes ||
      index_bytes > kMaximumJsonBytes - metadata_size) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::FormatBounds,
        "TH3DS file has trailing bytes or exceeds the metadata budget"));
  }

  Sha256Digest expected_catalog{};
  Sha256Digest expected_payload{};
  Sha256Digest expected_container{};
  Sha256Digest header_source{};
  std::copy_n(header.begin() + 0x68, 32U, expected_catalog.begin());
  std::copy_n(header.begin() + 0x88, 32U, expected_payload.begin());
  std::copy_n(header.begin() + 0xA8, 32U, expected_container.begin());
  std::copy_n(header.begin() + 0xC8, 32U, header_source.begin());
  if (header_source != family_source) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::SourceSetMixed,
        "package source-set differs from bundle source-set"));
  }
  const auto container_hash = hash_file(path, 0U, size, true);
  if (!container_hash) {
    return ResourceResult<MountedPackage>::failure(container_hash.error());
  }
  if (container_hash.value() != expected_container ||
      container_hash.value() != declaration.container) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::HashContainer,
        "TH3DS container SHA-256 mismatch: " + declaration.path));
  }
  const auto payload_hash = hash_file(path, data_offset, data_size);
  if (!payload_hash) return ResourceResult<MountedPackage>::failure(payload_hash.error());
  if (payload_hash.value() != expected_payload) {
    return ResourceResult<MountedPackage>::failure(
        error(ResourceErrorCode::HashPayload, "TH3DS payload SHA-256 mismatch"));
  }

  auto manifest_bytes = read_file_range(path, manifest_offset, manifest_size,
                                        kMaximumJsonBytes, "manifest");
  auto index = read_file_range(path, index_offset, index_bytes,
                               kMaximumJsonBytes, "index");
  auto metadata = read_file_range(path, metadata_offset, metadata_size,
                                  kMaximumJsonBytes, "metadata");
  if (!manifest_bytes) return ResourceResult<MountedPackage>::failure(manifest_bytes.error());
  if (!index) return ResourceResult<MountedPackage>::failure(index.error());
  if (!metadata) return ResourceResult<MountedPackage>::failure(metadata.error());
  Sha256 catalog_hash;
  catalog_hash.update(index.value().data(), index.value().size());
  catalog_hash.update(metadata.value().data(), metadata.value().size());
  if (catalog_hash.finish() != expected_catalog) {
    return ResourceResult<MountedPackage>::failure(
        error(ResourceErrorCode::HashCatalog, "TH3DS catalog SHA-256 mismatch"));
  }
  auto manifest_result = parse_canonical_json(
      {manifest_bytes.value().data(), manifest_bytes.value().size()},
      "package manifest");
  if (!manifest_result) {
    return ResourceResult<MountedPackage>::failure(manifest_result.error());
  }
  const Json& manifest = manifest_result.value();
  const Json* package = manifest.get("package");
  const Json* source = manifest.get("source");
  const Json* abi = manifest.get("runtime_abi");
  const Json* catalog = manifest.get("catalog");
  const Json* budgets = manifest.get("budgets");
  const Json* dependencies = manifest.get("dependencies");
  const Json* groups = manifest.get("groups");
  const Json* language = manifest.get("language");
  const Json* level = manifest.get("level");
  const Json* provenance = manifest.get("provenance");
  const Json* toolchain = manifest.get("toolchain");
  const std::string* package_name = package == nullptr ? nullptr : json_string(package->get("name"));
  const std::string* package_role_name = package == nullptr ? nullptr : json_string(package->get("role"));
  const std::string* package_hex = package == nullptr ? nullptr : json_string(package->get("id"));
  const std::string* source_hex = source == nullptr ? nullptr : json_string(source->get("set_sha256"));
  const std::string* catalog_hex = catalog == nullptr ? nullptr : json_string(catalog->get("catalog_sha256"));
  const std::string* payload_hex = catalog == nullptr ? nullptr : json_string(catalog->get("payload_sha256"));
  Sha256Digest manifest_source{};
  Sha256Digest manifest_catalog{};
  Sha256Digest manifest_payload{};
  PackageId manifest_package_id{};
  if (manifest.type != Json::Type::Object ||
      !json_version(manifest.get("format"), minor) ||
      package == nullptr || package->type != Json::Type::Object ||
      source == nullptr || source->type != Json::Type::Object ||
      abi == nullptr || abi->type != Json::Type::Object ||
      catalog == nullptr || catalog->type != Json::Type::Object ||
      budgets == nullptr || budgets->type != Json::Type::Object ||
      dependencies == nullptr || dependencies->type != Json::Type::Array ||
      groups == nullptr || groups->type != Json::Type::Array || groups->array.empty() ||
      provenance == nullptr || provenance->type != Json::Type::Object ||
      toolchain == nullptr || toolchain->type != Json::Type::Object ||
      package_name == nullptr || package_name->empty() ||
      !safe_bundle_path(*package_name) || package_name->find('/') != std::string::npos ||
      package_role_name == nullptr || *package_role_name != role_name(*package_role) ||
      package_hex == nullptr || !parse_hex16(*package_hex, manifest_package_id) ||
      source_hex == nullptr || !parse_sha256_hex(*source_hex, manifest_source) ||
      manifest_source != family_source ||
      json_unsigned(abi->get("min")) != kTh3dsRuntimeAbi ||
      json_unsigned(abi->get("max")) != kTh3dsRuntimeAbi ||
      json_unsigned(catalog->get("resource_count")) != index_count ||
      catalog_hex == nullptr || !parse_sha256_hex(*catalog_hex, manifest_catalog) ||
      payload_hex == nullptr || !parse_sha256_hex(*payload_hex, manifest_payload) ||
      manifest_catalog != expected_catalog || manifest_payload != expected_payload ||
      manifest_package_id != declaration.id ||
      manifest_package_id != package_id(*package_role, *package_name, family_source) ||
      !json_unsigned(source->get("file_count")) ||
      !json_unsigned(source->get("total_bytes")) ||
      json_boolean(provenance->get("contains_user_game_data")) != true ||
      json_boolean(provenance->get("redistributable")) != false) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::PackageMismatch,
        "TH3DS package manifest does not match its header or bundle"));
  }

  MountedPackage result;
  result.path = path;
  result.role = *package_role;
  result.name = *package_name;
  result.format_minor = minor;
  result.id = manifest_package_id;
  result.source_set_sha256 = family_source;
  result.container_sha256 = expected_container;
  std::set<PackageId> dependency_ids;
  for (const Json& row : dependencies->array) {
    PackageDependency dependency;
    const std::string* id = json_string(row.get("package_id"));
    const std::string* container = json_string(row.get("container_sha256"));
    if (row.type != Json::Type::Object || id == nullptr || container == nullptr ||
        !parse_hex16(*id, dependency.package_id) ||
        !parse_sha256_hex(*container, dependency.container_sha256) ||
        dependency.package_id == result.id ||
        !dependency_ids.insert(dependency.package_id).second) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "TH3DS package dependency declaration is invalid or duplicate"));
    }
    result.dependencies.push_back(dependency);
  }
  const bool language_null = json_null(language);
  const bool level_null = json_null(level);
  if ((*package_role == PackageRole::Core && (!language_null || !level_null)) ||
      (*package_role == PackageRole::Language &&
       (language == nullptr || language->type != Json::Type::Object || !level_null ||
        json_string(language->get("tag")) == nullptr ||
        *json_string(language->get("tag")) != *package_name)) ||
      (*package_role == PackageRole::Level &&
       (level == nullptr || level->type != Json::Type::Object || !language_null ||
        json_string(level->get("id")) == nullptr ||
        *json_string(level->get("id")) != *package_name))) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::PackageMismatch,
        "TH3DS role-specific language or level schema is invalid"));
  }
  const std::array<std::pair<const char*, ResourcePool>, 6> budget_fields{{
      {"audio_bytes", ResourcePool::Audio},
      {"sprite_bytes", ResourcePool::Sprite},
      {"texture_bytes", ResourcePool::Texture},
      {"language_font_bytes", ResourcePool::LanguageFont},
      {"metadata_bytes", ResourcePool::Metadata},
      {"scratch_bytes", ResourcePool::Scratch},
  }};
  for (const auto& field : budget_fields) {
    const auto value = json_unsigned(budgets->get(field.first));
    if (!value || *value > resource_pool_limit(field.second)) {
      return ResourceResult<MountedPackage>::failure(error(
          budget_error(field.second),
          std::string("package budget exceeds runtime cap: ") + field.first));
    }
    result.budgets.bytes[static_cast<std::size_t>(field.second)] = *value;
  }
  const std::uint64_t retained_metadata =
      metadata_size + static_cast<std::uint64_t>(index_count) *
                          static_cast<std::uint64_t>(sizeof(ResourceDescriptor) +
                                                     sizeof(const ResourceDescriptor*));
  if (retained_metadata >
      result.budgets.bytes[static_cast<std::size_t>(ResourcePool::Metadata)]) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::BudgetMetadata,
        "package catalog exceeds its declared metadata budget"));
  }

  result.metadata = std::move(metadata.value());
  result.resources.reserve(index_count);
  ResourceId previous_id{};
  bool has_previous = false;
  struct PayloadInterval {
    std::uint64_t begin;
    std::uint64_t end;
  };
  std::vector<PayloadInterval> intervals;
  intervals.reserve(index_count);
  for (std::uint32_t row = 0U; row < index_count; ++row) {
    const std::uint8_t* entry = index.value().data() + row * kIndexEntrySize;
    ResourceDescriptor descriptor;
    std::copy_n(entry, descriptor.id.size(), descriptor.id.begin());
    if (has_previous && !(previous_id < descriptor.id)) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::IdDuplicate,
          "TH3DS resource IDs are duplicate or out of order", descriptor.id));
    }
    previous_id = descriptor.id;
    has_previous = true;
    const auto kind = parse_kind(read_le<std::uint16_t>(entry + 0x10));
    const std::uint16_t codec = read_le<std::uint16_t>(entry + 0x12);
    descriptor.flags = read_le<std::uint32_t>(entry + 0x14);
    descriptor.group_id = read_le<std::uint32_t>(entry + 0x18);
    const std::uint8_t alignment_log2 = entry[0x1C];
    if (!kind || codec > 2U || (descriptor.flags & ~kKnownFlags) != 0U ||
        entry[0x1D] != 0U || entry[0x1E] != 0U || entry[0x1F] != 0U) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::UnsupportedFeature,
          "TH3DS resource uses an unknown kind, codec, flag or reserved byte",
          descriptor.id));
    }
    if (codec != 0U) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::UnsupportedCodec,
          "TH3DS v1 runtime requires outer codec NONE", descriptor.id));
    }
    descriptor.kind = *kind;
    descriptor.codec = ResourceCodec::None;
    descriptor.alignment = alignment_log2 == 6U
                               ? static_cast<std::uint32_t>(kDefaultAlignment)
                               : (alignment_log2 == 12U
                                      ? static_cast<std::uint32_t>(kAudioAlignment)
                                      : 0U);
    descriptor.data_offset = read_le<std::uint64_t>(entry + 0x20);
    descriptor.stored_size = read_le<std::uint32_t>(entry + 0x28);
    descriptor.decoded_size = read_le<std::uint32_t>(entry + 0x2C);
    const std::uint64_t meta_relative = read_le<std::uint64_t>(entry + 0x30);
    descriptor.metadata_size = read_le<std::uint32_t>(entry + 0x38);
    descriptor.dependency_count = read_le<std::uint16_t>(entry + 0x3C);
    const std::uint16_t entry_reserved = read_le<std::uint16_t>(entry + 0x3E);
    std::copy_n(entry + 0x40, 32U, descriptor.stored_sha256.begin());
    std::copy_n(entry + 0x60, 32U, descriptor.decoded_sha256.begin());
    descriptor.metadata_offset = metadata_offset + meta_relative;
    std::uint64_t resource_end = 0U;
    std::uint64_t metadata_end = 0U;
    const std::uint64_t dependency_bytes =
        static_cast<std::uint64_t>(descriptor.dependency_count) * 16U;
    if (descriptor.alignment == 0U ||
        descriptor.data_offset % descriptor.alignment != 0U ||
        descriptor.data_offset < data_offset ||
        descriptor.stored_size > kMaximumResourceBytes ||
        descriptor.decoded_size > kMaximumResourceBytes ||
        !checked_add(descriptor.data_offset, descriptor.stored_size, resource_end) ||
        resource_end > data_offset + data_size || meta_relative > metadata_size ||
        !checked_add(meta_relative, descriptor.metadata_size, metadata_end) ||
        metadata_end > metadata_size || dependency_bytes > descriptor.metadata_size ||
        entry_reserved != 0U) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::FormatBounds,
          "TH3DS resource range or dependency metadata is invalid", descriptor.id));
    }
    if (!resource_contract_allowed(descriptor, result.role)) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::UnsupportedFeature,
          "TH3DS resource role, kind, flags, group or alignment is invalid",
          descriptor.id));
    }
    std::set<ResourceId> dependency_ids_for_resource;
    descriptor.dependencies.reserve(descriptor.dependency_count);
    for (std::uint16_t dependency_index = 0U;
         dependency_index < descriptor.dependency_count; ++dependency_index) {
      ResourceId dependency{};
      const std::size_t dependency_offset =
          static_cast<std::size_t>(meta_relative) +
          static_cast<std::size_t>(dependency_index) * dependency.size();
      std::copy_n(result.metadata.data() + dependency_offset,
                  dependency.size(), dependency.begin());
      if (dependency == descriptor.id ||
          !dependency_ids_for_resource.insert(dependency).second) {
        return ResourceResult<MountedPackage>::failure(error(
            ResourceErrorCode::PackageMismatch,
            "TH3DS resource dependency is self-referential or duplicate",
            descriptor.id));
      }
      descriptor.dependencies.push_back(dependency);
    }
    const std::size_t json_offset =
        static_cast<std::size_t>(meta_relative + dependency_bytes);
    const std::size_t json_size =
        static_cast<std::size_t>(descriptor.metadata_size - dependency_bytes);
    auto resource_metadata = parse_canonical_json(
        {result.metadata.data() + json_offset, json_size}, "resource metadata");
    if (!resource_metadata) {
      ResourceError metadata_error = resource_metadata.error();
      metadata_error.resource_id = descriptor.id;
      return ResourceResult<MountedPackage>::failure(std::move(metadata_error));
    }
    if (!resource_metadata_allowed(descriptor, resource_metadata.value())) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "TH3DS resource metadata does not match its kind", descriptor.id));
    }
    if (descriptor.kind == ResourceKind::LanguageBundle &&
        *json_string(resource_metadata.value().get("tag")) != result.name) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "language resource tag differs from its package name", descriptor.id));
    }
    const auto stored_hash = hash_file(path, descriptor.data_offset,
                                       descriptor.stored_size);
    if (!stored_hash) {
      return ResourceResult<MountedPackage>::failure(stored_hash.error());
    }
    if (stored_hash.value() != descriptor.stored_sha256) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::HashResource,
          "TH3DS stored resource SHA-256 mismatch", descriptor.id));
    }
    intervals.push_back({descriptor.data_offset, resource_end});
    result.resources.push_back(descriptor);
  }
  std::sort(intervals.begin(), intervals.end(),
            [](const PayloadInterval& left, const PayloadInterval& right) {
              return left.begin < right.begin;
            });
  std::uint64_t cursor = data_offset;
  for (const PayloadInterval& interval : intervals) {
    if (interval.begin < cursor) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::FormatBounds,
          "TH3DS resource payloads overlap"));
    }
    const auto padding =
        require_zero_range(path, cursor, interval.begin - cursor, "resource");
    if (!padding) return ResourceResult<MountedPackage>::failure(padding.error());
    cursor = interval.end;
  }
  const auto trailing =
      require_zero_range(path, cursor, data_offset + data_size - cursor, "end");
  if (!trailing) return ResourceResult<MountedPackage>::failure(trailing.error());
  std::set<std::uint32_t> group_ids;
  std::set<ResourceId> grouped_resources;
  for (const Json& row : groups->array) {
    const auto id = json_unsigned(row.get("id"));
    const std::string* name = json_string(row.get("name"));
    const auto required = json_boolean(row.get("required"));
    const auto ceiling = json_unsigned(row.get("decoded_ceiling_bytes"));
    const Json* ids = row.get("resource_ids");
    if (row.type != Json::Type::Object || !id || *id == 0U ||
        *id > std::numeric_limits<std::uint32_t>::max() || name == nullptr ||
        name->empty() || !safe_bundle_path(*name) || name->find('/') != std::string::npos ||
        !required || !ceiling || *ceiling > kMaximumResourceBytes ||
        ids == nullptr || ids->type != Json::Type::Array || ids->array.empty() ||
        !group_ids.insert(static_cast<std::uint32_t>(*id)).second) {
      return ResourceResult<MountedPackage>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "TH3DS resource group schema is invalid or duplicate"));
    }
    ResourceGroup group;
    group.id = static_cast<std::uint32_t>(*id);
    group.name = *name;
    group.required = *required;
    group.decoded_ceiling_bytes = *ceiling;
    ResourceId previous_group_id{};
    bool has_previous_group_id = false;
    for (const Json& encoded_id : ids->array) {
      ResourceId resource_id{};
      const std::string* value = json_string(&encoded_id);
      if (value == nullptr || !parse_resource_id_hex(*value, resource_id) ||
          (has_previous_group_id && !(previous_group_id < resource_id)) ||
          !grouped_resources.insert(resource_id).second) {
        return ResourceResult<MountedPackage>::failure(error(
            ResourceErrorCode::PackageMismatch,
            "TH3DS group resource IDs are invalid, duplicate or unordered"));
      }
      const auto resource = std::find_if(
          result.resources.begin(), result.resources.end(),
          [&resource_id](const ResourceDescriptor& descriptor) {
            return descriptor.id == resource_id;
          });
      if (resource == result.resources.end() || resource->group_id != group.id) {
        return ResourceResult<MountedPackage>::failure(error(
            ResourceErrorCode::PackageMismatch,
            "TH3DS group membership disagrees with the resource index",
            resource_id));
      }
      group.resource_ids.push_back(resource_id);
      previous_group_id = resource_id;
      has_previous_group_id = true;
    }
    result.groups.push_back(std::move(group));
  }
  if (grouped_resources.size() != result.resources.size()) {
    return ResourceResult<MountedPackage>::failure(error(
        ResourceErrorCode::PackageMismatch,
        "TH3DS package groups do not cover every resource exactly once"));
  }
  return ResourceResult<MountedPackage>::success(std::move(result));
}

ResourceResult<void> validate_mounted_family(
    const std::vector<MountedPackage>& packages) {
  std::map<PackageId, const MountedPackage*> package_by_id;
  std::map<ResourceId, const ResourceDescriptor*> resource_by_id;
  std::size_t core_count = 0U;
  std::size_t language_count = 0U;
  std::size_t level_count = 0U;
  for (const MountedPackage& package : packages) {
    if (!package_by_id.emplace(package.id, &package).second) {
      return ResourceResult<void>::failure(error(
          ResourceErrorCode::IdDuplicate,
          "mounted package family contains a duplicate package ID"));
    }
    core_count += package.role == PackageRole::Core ? 1U : 0U;
    language_count += package.role == PackageRole::Language ? 1U : 0U;
    level_count += package.role == PackageRole::Level ? 1U : 0U;
    std::size_t language_roots = 0U;
    for (const ResourceDescriptor& descriptor : package.resources) {
      if (!resource_by_id.emplace(descriptor.id, &descriptor).second) {
        return ResourceResult<void>::failure(error(
            ResourceErrorCode::IdDuplicate,
            "mounted package family contains a duplicate resource ID",
            descriptor.id));
      }
      if (descriptor.kind == ResourceKind::LanguageBundle) ++language_roots;
    }
    if ((package.role == PackageRole::Language && language_roots != 1U) ||
        (package.role != PackageRole::Language && language_roots != 0U)) {
      return ResourceResult<void>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "language package cardinality is invalid"));
    }
  }
  if (core_count != 1U || language_count != 1U || level_count > 1U) {
    return ResourceResult<void>::failure(error(
        ResourceErrorCode::PackageMismatch,
        "mounted family must contain one core, one language and at most one level"));
  }
  const auto core = std::find_if(
      packages.begin(), packages.end(),
      [](const MountedPackage& package) { return package.role == PackageRole::Core; });
  for (const MountedPackage& package : packages) {
    if (package.role == PackageRole::Core && !package.dependencies.empty()) {
      return ResourceResult<void>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "core package cannot depend on another package"));
    }
    bool depends_on_core = package.role == PackageRole::Core;
    for (const PackageDependency& dependency : package.dependencies) {
      const auto mounted = package_by_id.find(dependency.package_id);
      if (mounted == package_by_id.end() ||
          mounted->second->container_sha256 != dependency.container_sha256) {
        return ResourceResult<void>::failure(error(
            ResourceErrorCode::PackageMismatch,
            "package dependency is absent or has a different container hash"));
      }
      depends_on_core = depends_on_core || dependency.package_id == core->id;
    }
    if (!depends_on_core) {
      return ResourceResult<void>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "language and level packages must explicitly depend on core"));
    }
  }

  std::map<ResourceId, std::uint8_t> visit;
  std::function<ResourceResult<void>(const ResourceDescriptor&)> walk;
  walk = [&resource_by_id, &visit, &walk](const ResourceDescriptor& descriptor)
      -> ResourceResult<void> {
    std::uint8_t& state = visit[descriptor.id];
    if (state == 2U) return ResourceResult<void>::success();
    if (state == 1U) {
      return ResourceResult<void>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "resource dependency graph contains a cycle", descriptor.id));
    }
    state = 1U;
    for (const ResourceId& dependency_id : descriptor.dependencies) {
      const auto dependency = resource_by_id.find(dependency_id);
      if (dependency == resource_by_id.end() ||
          !dependency_kind_allowed(descriptor.kind, dependency->second->kind) ||
          dependency->second->group_id > descriptor.group_id) {
        return ResourceResult<void>::failure(error(
            ResourceErrorCode::PackageMismatch,
            "resource dependency is missing, has the wrong kind or outlives its group",
            descriptor.id));
      }
      auto nested = walk(*dependency->second);
      if (!nested) return nested;
    }
    state = 2U;
    return ResourceResult<void>::success();
  };
  for (const auto& item : resource_by_id) {
    auto valid = walk(*item.second);
    if (!valid) return valid;
  }
  return ResourceResult<void>::success();
}

}  // namespace

const ResourceDescriptor* ResourceCatalog::find(const ResourceId& id) const noexcept {
  const auto iterator = std::lower_bound(
      sorted_.begin(), sorted_.end(), id,
      [](const ResourceDescriptor* descriptor, const ResourceId& value) {
        return descriptor->id < value;
      });
  return iterator == sorted_.end() || (*iterator)->id != id ? nullptr : *iterator;
}

ResourceResult<ResourceCatalog> ResourceCatalog::build(
    std::vector<MountedPackage>& packages) {
  ResourceCatalog result;
  std::size_t count = 0U;
  for (const MountedPackage& package : packages) count += package.resources.size();
  result.sorted_.reserve(count);
  for (std::size_t package_index = 0U; package_index < packages.size();
       ++package_index) {
    for (ResourceDescriptor& descriptor : packages[package_index].resources) {
      descriptor.package_index = package_index;
      result.sorted_.push_back(&descriptor);
    }
  }
  std::sort(result.sorted_.begin(), result.sorted_.end(),
            [](const ResourceDescriptor* left, const ResourceDescriptor* right) {
              return left->id < right->id;
            });
  for (std::size_t index = 1U; index < result.sorted_.size(); ++index) {
    if (result.sorted_[index - 1U]->id == result.sorted_[index]->id) {
      return ResourceResult<ResourceCatalog>::failure(error(
          ResourceErrorCode::IdDuplicate,
          "resource ID is duplicated across mounted packages",
          result.sorted_[index]->id));
    }
  }
  return ResourceResult<ResourceCatalog>::success(std::move(result));
}

ResourceResult<const ResourceDescriptor*> ResourceCatalog::find(
    const ResourceId& id, ResourceKind expected_kind) const {
  const ResourceDescriptor* descriptor = find(id);
  if (descriptor == nullptr) {
    return ResourceResult<const ResourceDescriptor*>::failure(error(
        ResourceErrorCode::ResourceNotFound,
        "resource ID is not present in the mounted catalog", id));
  }
  if (descriptor->kind != expected_kind) {
    return ResourceResult<const ResourceDescriptor*>::failure(error(
        ResourceErrorCode::KindMismatch,
        "resource kind differs from typed lookup", id));
  }
  return ResourceResult<const ResourceDescriptor*>::success(descriptor);
}

static ResourceResult<std::shared_ptr<MountedBundle>> open_bundle_impl(
    const std::filesystem::path& bundle_manifest) {
  const auto size_result = runtime_file_size(bundle_manifest);
  if (!size_result) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(size_result.error());
  }
  if (size_result.value() == 0U || size_result.value() > kMaximumJsonBytes) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::FormatCanonicalJson,
        "bundle manifest size is invalid"));
  }
  auto encoded = read_file_range(bundle_manifest, 0U, size_result.value(),
                                 kMaximumJsonBytes, "bundle manifest");
  if (!encoded) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(encoded.error());
  }
  auto parsed = parse_canonical_json({encoded.value().data(), encoded.value().size()},
                                     "bundle manifest");
  if (!parsed) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(parsed.error());
  }
  Json bundle = std::move(parsed.value());
  const std::string* digest_hex = json_string(bundle.get("bundle_sha256"));
  const std::string* source_hex = json_string(bundle.get("source_set_sha256"));
  const std::string* selected = json_string(bundle.get("selected_language"));
  const Json* fallback_value = bundle.get("fallback_language");
  const Json* start_level_value = bundle.get("start_level");
  const Json* packages = bundle.get("packages");
  Sha256Digest expected_bundle{};
  Sha256Digest source{};
  if (bundle.type != Json::Type::Object || !json_version(bundle.get("format")) ||
      json_unsigned(bundle.get("runtime_abi")) != kTh3dsRuntimeAbi ||
      digest_hex == nullptr || !parse_sha256_hex(*digest_hex, expected_bundle) ||
      source_hex == nullptr || !parse_sha256_hex(*source_hex, source) ||
      selected == nullptr || selected->empty() || packages == nullptr ||
      packages->type != Json::Type::Array || packages->array.empty() ||
      (fallback_value != nullptr && !json_null(fallback_value) &&
       json_string(fallback_value) == nullptr) ||
      (start_level_value != nullptr && !json_null(start_level_value) &&
       json_string(start_level_value) == nullptr)) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::PackageMismatch,
        "bundle manifest is missing a required v1 field"));
  }
  bundle.object["bundle_sha256"].string.assign(64U, '0');
  std::string zeroed;
  encode_json(bundle, zeroed);
  if (sha256(zeroed.data(), zeroed.size()) != expected_bundle) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(
        error(ResourceErrorCode::HashBundle, "bundle manifest SHA-256 mismatch"));
  }

  std::vector<PackageDeclaration> declarations;
  declarations.reserve(packages->array.size());
  std::string previous_path;
  std::set<PackageId> package_ids;
  for (const Json& row : packages->array) {
    const std::string* path = json_string(row.get("path"));
    const std::string* role = json_string(row.get("role"));
    const std::string* id = json_string(row.get("package_id"));
    const std::string* container = json_string(row.get("container_sha256"));
    const auto bytes = json_unsigned(row.get("size"));
    PackageDeclaration declaration;
    if (row.type != Json::Type::Object || path == nullptr || !safe_bundle_path(*path) ||
        (!previous_path.empty() && *path <= previous_path) || role == nullptr ||
        id == nullptr || !parse_hex16(*id, declaration.id) || container == nullptr ||
        !parse_sha256_hex(*container, declaration.container) || !bytes || *bytes == 0U) {
      return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "bundle package declaration is invalid, duplicate or out of order"));
    }
    if (*role == "core") declaration.role = PackageRole::Core;
    else if (*role == "language") declaration.role = PackageRole::Language;
    else if (*role == "level") declaration.role = PackageRole::Level;
    else {
      return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
          ResourceErrorCode::PackageMismatch, "bundle package role is invalid"));
    }
    if (!canonical_package_path(*path, declaration.role)) {
      return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
          ResourceErrorCode::PackageMismatch,
          "bundle package path does not match its role"));
    }
    if (!package_ids.insert(declaration.id).second) {
      return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
          ResourceErrorCode::IdDuplicate, "bundle contains a duplicate package ID"));
    }
    declaration.path = *path;
    declaration.size = *bytes;
    previous_path = *path;
    declarations.push_back(std::move(declaration));
  }

  const std::filesystem::path root = bundle_manifest.parent_path();
  const std::string selected_path = "lang/" + *selected + ".th3ds";
  const std::string* fallback = json_string(fallback_value);
  const std::string fallback_path =
      fallback == nullptr ? std::string{} : "lang/" + *fallback + ".th3ds";
  const std::string* start_level = json_string(start_level_value);
  const std::string level_path = start_level == nullptr
                                     ? std::string{}
                                     : "level/" + *start_level + ".th3ds";
  if (!safe_bundle_path(selected_path) ||
      (!fallback_path.empty() && !safe_bundle_path(fallback_path)) ||
      (!level_path.empty() && !safe_bundle_path(level_path)) ||
      (!fallback_path.empty() && fallback_path == selected_path)) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::PackageMismatch,
        "bundle language or level identifier is not a safe canonical path"));
  }

  auto find_declaration = [&declarations](const std::string& path,
                                          PackageRole role)
      -> const PackageDeclaration* {
    const auto iterator = std::find_if(
        declarations.begin(), declarations.end(),
        [&path, role](const PackageDeclaration& item) {
          return item.path == path && item.role == role;
        });
    return iterator == declarations.end() ? nullptr : &*iterator;
  };
  const std::size_t declared_cores = static_cast<std::size_t>(std::count_if(
      declarations.begin(), declarations.end(), [](const PackageDeclaration& item) {
        return item.role == PackageRole::Core;
      }));
  if (declared_cores != 1U) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::PackageMismatch,
        "bundle must declare exactly one canonical core package"));
  }
  const PackageDeclaration* core = find_declaration("core.th3ds", PackageRole::Core);
  if (core == nullptr) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::PackageMissing,
        "bundle is missing its canonical core package"));
  }
  const PackageDeclaration* level_declaration =
      level_path.empty() ? nullptr
                         : find_declaration(level_path, PackageRole::Level);
  if (!level_path.empty() && level_declaration == nullptr) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::PackageMissing,
        "bundle is missing its explicitly selected start-level package"));
  }

  auto attempt = [&](const std::string& language_name,
                     const PackageDeclaration* language_declaration)
      -> ResourceResult<std::shared_ptr<MountedBundle>> {
    if (language_declaration == nullptr) {
      return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
          ResourceErrorCode::PackageMissing,
          "bundle is missing the declared language package"));
    }
    auto result = std::make_shared<MountedBundle>();
    result->root = root;
    result->selected_language = language_name;
    if (fallback != nullptr) result->fallback_language = *fallback;
    if (start_level != nullptr) result->start_level = *start_level;
    result->bundle_sha256 = expected_bundle;
    result->source_set_sha256 = source;
    std::vector<const PackageDeclaration*> selected_packages{core,
                                                              language_declaration};
    if (level_declaration != nullptr) selected_packages.push_back(level_declaration);
    result->packages.reserve(selected_packages.size());
    for (const PackageDeclaration* declaration : selected_packages) {
      auto safe_path = safe_package_file(root, declaration->path);
      if (!safe_path) {
        return ResourceResult<std::shared_ptr<MountedBundle>>::failure(
            safe_path.error());
      }
      auto mounted = mount_package(safe_path.value(), *declaration, source);
      if (!mounted) {
        return ResourceResult<std::shared_ptr<MountedBundle>>::failure(mounted.error());
      }
      result->packages.push_back(std::move(mounted.value()));
    }
    auto family = validate_mounted_family(result->packages);
    if (!family) {
      return ResourceResult<std::shared_ptr<MountedBundle>>::failure(family.error());
    }
    std::size_t metadata_total = 0U;
    for (MountedPackage& package : result->packages) {
      const std::size_t descriptor_bytes =
          package.resources.size() * sizeof(ResourceDescriptor);
      const std::size_t catalog_bytes =
          package.resources.size() * sizeof(const ResourceDescriptor*);
      if (package.metadata.size() > static_cast<std::size_t>(resource_pool_limit(
                                        ResourcePool::Metadata)) - metadata_total ||
          descriptor_bytes > static_cast<std::size_t>(resource_pool_limit(
                                  ResourcePool::Metadata)) - metadata_total -
                                 package.metadata.size() ||
          catalog_bytes > static_cast<std::size_t>(resource_pool_limit(
                               ResourcePool::Metadata)) - metadata_total -
                              package.metadata.size() - descriptor_bytes) {
        return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
            ResourceErrorCode::BudgetMetadata,
            "mounted catalogs exceed the 1 MiB metadata pool"));
      }
      metadata_total += package.metadata.size() + descriptor_bytes + catalog_bytes;
    }
    auto catalog_result = ResourceCatalog::build(result->packages);
    if (!catalog_result) {
      return ResourceResult<std::shared_ptr<MountedBundle>>::failure(
          catalog_result.error());
    }
    result->catalog = std::move(catalog_result.value());
    return ResourceResult<std::shared_ptr<MountedBundle>>::success(std::move(result));
  };

  const PackageDeclaration* selected_declaration =
      find_declaration(selected_path, PackageRole::Language);
  auto selected_attempt = attempt(*selected, selected_declaration);
  if (selected_attempt || fallback == nullptr) return selected_attempt;
  const PackageDeclaration* fallback_declaration =
      find_declaration(fallback_path, PackageRole::Language);
  return attempt(*fallback, fallback_declaration);
}

ResourceResult<std::shared_ptr<MountedBundle>> BundleMount::open_bundle(
    const std::filesystem::path& bundle_manifest) {
  try {
    return open_bundle_impl(bundle_manifest);
  } catch (const std::bad_alloc&) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::AllocationFailed,
        "bundle mount allocation failed"));
  } catch (const std::exception&) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::Internal,
        "bundle mount caught an internal exception"));
  } catch (...) {
    return ResourceResult<std::shared_ptr<MountedBundle>>::failure(error(
        ResourceErrorCode::Internal,
        "bundle mount caught an unknown exception"));
  }
}

ResourceResult<void> read_resource_range(
    const MountedBundle& bundle, const ResourceDescriptor& descriptor,
    std::uint64_t relative_offset, MutableByteView destination) {
  if (descriptor.package_index >= bundle.packages.size() ||
      relative_offset > descriptor.stored_size ||
      destination.size > descriptor.stored_size - relative_offset ||
      (destination.size != 0U && destination.data == nullptr)) {
    return ResourceResult<void>::failure(error(
        ResourceErrorCode::FormatBounds,
        "resource range read is out of bounds", descriptor.id));
  }
  std::uint64_t absolute = 0U;
  if (!checked_add(descriptor.data_offset, relative_offset, absolute) ||
      absolute > static_cast<std::uint64_t>(
                     std::numeric_limits<std::streamoff>::max()) ||
      destination.size > static_cast<std::size_t>(
                             std::numeric_limits<std::streamsize>::max())) {
    return ResourceResult<void>::failure(error(
        ResourceErrorCode::FormatBounds,
        "resource range read overflows the platform", descriptor.id));
  }
  std::ifstream stream(bundle.packages[descriptor.package_index].path,
                       std::ios::binary);
  if (!stream) {
    return ResourceResult<void>::failure(error(
        ResourceErrorCode::Io, "cannot reopen mounted TH3DS package", descriptor.id));
  }
  stream.seekg(static_cast<std::streamoff>(absolute), std::ios::beg);
  if (destination.size != 0U) {
    stream.read(reinterpret_cast<char*>(destination.data),
                static_cast<std::streamsize>(destination.size));
  }
  if (!stream || stream.gcount() != static_cast<std::streamsize>(destination.size)) {
    return ResourceResult<void>::failure(error(
        ResourceErrorCode::Io, "truncated resource range read", descriptor.id));
  }
  return ResourceResult<void>::success();
}

std::string resource_id_hex(const ResourceId& id) {
  constexpr char digits[] = "0123456789abcdef";
  std::string result(32U, '0');
  for (std::size_t index = 0U; index < id.size(); ++index) {
    result[index * 2U] = digits[id[index] >> 4U];
    result[index * 2U + 1U] = digits[id[index] & 0x0FU];
  }
  return result;
}

bool parse_resource_id_hex(std::string_view value, ResourceId& id) noexcept {
  if (value.size() != 32U) return false;
  for (std::size_t index = 0U; index < id.size(); ++index) {
    const auto digit = [](char character) noexcept -> int {
      if (character >= '0' && character <= '9') return character - '0';
      if (character >= 'a' && character <= 'f') return character - 'a' + 10;
      return -1;
    };
    const int high = digit(value[index * 2U]);
    const int low = digit(value[index * 2U + 1U]);
    if (high < 0 || low < 0) return false;
    id[index] = static_cast<std::uint8_t>((high << 4) | low);
  }
  return true;
}

const char* resource_kind_name(ResourceKind kind) noexcept {
  switch (kind) {
    case ResourceKind::AudioBank: return "AUDIO_BANK";
    case ResourceKind::LanguageBundle: return "LANGUAGE_BUNDLE";
    case ResourceKind::SpriteSheet: return "SPRITE_SHEET";
    case ResourceKind::UiBitmap: return "UI_BITMAP";
    case ResourceKind::FontAtlas: return "FONT_ATLAS";
    case ResourceKind::FontMap: return "FONT_MAP";
    case ResourceKind::Palette: return "PALETTE";
    case ResourceKind::OpaqueBlob: return "OPAQUE_BLOB";
  }
  return "UNKNOWN";
}

const char* resource_error_name(ResourceErrorCode code) noexcept {
  switch (code) {
    case ResourceErrorCode::None: return "OK";
    case ResourceErrorCode::Io: return "E_IO";
    case ResourceErrorCode::LegacyAuditPack: return "E_LEGACY_AUDIT_PACK";
    case ResourceErrorCode::FormatMagic: return "E_FORMAT_MAGIC";
    case ResourceErrorCode::HeaderReserved: return "E_HEADER_RESERVED";
    case ResourceErrorCode::FormatMajor: return "E_FORMAT_MAJOR";
    case ResourceErrorCode::FormatMinor: return "E_FORMAT_MINOR";
    case ResourceErrorCode::UnsupportedFeature: return "E_UNSUPPORTED_FEATURE";
    case ResourceErrorCode::UnsupportedCodec: return "E_UNSUPPORTED_CODEC";
    case ResourceErrorCode::FormatBounds: return "E_FORMAT_BOUNDS";
    case ResourceErrorCode::FormatCanonicalJson: return "E_FORMAT_CANONICAL_JSON";
    case ResourceErrorCode::RuntimeAbi: return "E_RUNTIME_ABI";
    case ResourceErrorCode::HashBundle: return "E_HASH_BUNDLE";
    case ResourceErrorCode::HashContainer: return "E_HASH_CONTAINER";
    case ResourceErrorCode::HashCatalog: return "E_HASH_CATALOG";
    case ResourceErrorCode::HashPayload: return "E_HASH_PAYLOAD";
    case ResourceErrorCode::HashResource: return "E_HASH_RESOURCE";
    case ResourceErrorCode::HashDecoded: return "E_HASH_DECODED";
    case ResourceErrorCode::SourceSetMixed: return "E_SOURCE_SET_MIXED";
    case ResourceErrorCode::IdDuplicate: return "E_ID_DUPLICATE";
    case ResourceErrorCode::PackageMissing: return "E_PACKAGE_MISSING";
    case ResourceErrorCode::PackageMismatch: return "E_PACKAGE_MISMATCH";
    case ResourceErrorCode::ResourceNotFound: return "E_RESOURCE_NOT_FOUND";
    case ResourceErrorCode::KindMismatch: return "E_KIND_MISMATCH";
    case ResourceErrorCode::StreamRequired: return "E_STREAM_REQUIRED";
    case ResourceErrorCode::BudgetContract: return "E_BUDGET_CONTRACT";
    case ResourceErrorCode::BudgetAudio: return "E_BUDGET_AUDIO";
    case ResourceErrorCode::BudgetSprite: return "E_BUDGET_SPRITE";
    case ResourceErrorCode::BudgetTexture: return "E_BUDGET_TEXTURE";
    case ResourceErrorCode::BudgetLanguageFont: return "E_BUDGET_LANGUAGE_FONT";
    case ResourceErrorCode::BudgetMetadata: return "E_BUDGET_METADATA";
    case ResourceErrorCode::BudgetScratch: return "E_BUDGET_SCRATCH";
    case ResourceErrorCode::AllocationFailed: return "E_ALLOCATION_FAILED";
    case ResourceErrorCode::AccountingOverrun: return "E_ACCOUNTING_OVERRUN";
    case ResourceErrorCode::RefcountCorrupt: return "E_REFCOUNT_CORRUPT";
    case ResourceErrorCode::ScratchBusy: return "E_SCRATCH_BUSY";
    case ResourceErrorCode::GroupBusy: return "E_GROUP_BUSY";
    case ResourceErrorCode::TransitionReserve: return "E_TRANSITION_RESERVE";
    case ResourceErrorCode::SaveReserve: return "E_SAVE_RESERVE";
    case ResourceErrorCode::Internal: return "E_INTERNAL";
  }
  return "E_UNKNOWN";
}

}  // namespace cth3ds
