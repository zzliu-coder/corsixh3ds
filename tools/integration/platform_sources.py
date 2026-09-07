"""Read the deliberately small shared CMake source registry; reject omissions."""
from pathlib import Path, PurePosixPath
import re
import sys


def platform_files(root: Path) -> tuple[list[str], list[str]]:
    text = '\n'.join(line.split('#', 1)[0] for line in (root / 'sources.cmake').read_text().splitlines())
    pattern = r'set\(CTH3DS_PLATFORM_(SOURCES|HEADERS)\s+([^)]*)\)'
    blocks = re.findall(pattern, text)
    if re.sub(pattern, '', text).strip() or [key for key, _ in blocks] != ['SOURCES', 'HEADERS']:
        raise ValueError('invalid 3DS source registry syntax')
    sources, headers = [body.split() for _, body in blocks]
    registered = sources + headers
    if not sources or not headers or len(registered) != len(set(registered)):
        raise ValueError('empty or duplicate 3DS source registry')
    for group, suffix in ((sources, '.cpp'), (headers, '.hpp')):
        for name in group:
            path = PurePosixPath(name)
            if not re.fullmatch(r'[A-Za-z0-9_/.-]+', name) or path.is_absolute() or '..' in path.parts or path.suffix != suffix:
                raise ValueError('invalid 3DS source path: ' + name)
            if name != path.as_posix() or (root / path).is_symlink() or not (root / path).is_file():
                raise ValueError('missing or nonregular 3DS source: ' + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.suffix in ('.cpp', '.hpp')}
    if actual != set(registered):
        raise ValueError('unregistered 3DS source files: ' + repr(sorted(actual ^ set(registered))))
    return sources, headers


if __name__ == '__main__':
    for name in platform_files(Path(sys.argv[1]))[0]:
        print(name)
