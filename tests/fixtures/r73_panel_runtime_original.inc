// Fixed Runtime Panel contracts from 17603cb2ba832d57de7d3926b680cf6d5fabe610.
  void set_state(BottomUiState state) {
    if (bottom_ui_.state() == state) {
      return;
    }
    const BottomTab previous_tab = bottom_ui_.state().active_tab;
    bottom_ui_.set_state(std::move(state));
    if (previous_tab != bottom_ui_.state().active_tab) {
      scheduler_.request_redraw();
    }
    dirty_ = true;
  }

  void request_redraw() noexcept {
    dirty_ = true;
    scheduler_.request_redraw();
  }

  void force_render_bottom() {
    dirty_ = true;
    if (bottom_mode_ == BottomScreenMode::Game) {
      // Game pixels are published only by after_frame, after SDL_RenderFlush.
      // A UI/lifecycle notification may arrive while draw commands are queued.
      scheduler_.request_redraw();
    } else {
      render_bottom();
    }
  }

  void set_notice(std::string notice, bool is_error) {
    BottomUiState copy = bottom_ui_.state();
    if (copy.notice == notice && copy.notice_is_error == is_error) {
      return;
    }
    copy.notice = std::move(notice);
    notice_until_us_ = now_us() + 4000000U;
    copy.notice_is_error = is_error;
    bottom_ui_.set_state(std::move(copy));
    dirty_ = true;
    scheduler_.request_redraw();
  }

  void render_bottom() {
    if (bottom_window_ == nullptr) {
      return;
    }
    bottom_surface_ = SDL_GetWindowSurface(bottom_window_);
    if (bottom_surface_ == nullptr) {
      return;
    }
    if (!bottom_canvas_) {
      bottom_canvas_ = std::make_unique<SoftwareCanvas>(
          ScreenLayout::kBottomWidth, ScreenLayout::kBottomHeight);
      boot_log("runtime: legacy panel canvas allocated on demand");
    }
    render_bottom_ui(*bottom_canvas_, bottom_ui_);
    present_bottom_canvas();
  }

  void present_bottom_canvas() {
    if (bottom_window_ == nullptr) {
      return;
    }
    const bool must_lock = SDL_MUSTLOCK(bottom_surface_) != 0;
    if (must_lock && SDL_LockSurface(bottom_surface_) != 0) {
      return;
    }
    int conversion = 0;
    if (bottom_surface_->format->format == SDL_PIXELFORMAT_RGBA8888 &&
        bottom_surface_->w == ScreenLayout::kBottomWidth &&
        bottom_surface_->h == ScreenLayout::kBottomHeight &&
        bottom_surface_->pitch % 4 == 0) {
      // The N3DS display mode is RGBA8888, which is our RGBA byte order with
      // the word reversed. A byte swap is a single ARM `rev` instruction per
      // pixel; SDL_ConvertPixels would run the generic per-pixel blit
      // converter over the whole 320x240 surface every repaint instead.
      const auto& bytes = bottom_canvas_->rgba_bytes();
      const auto* source = reinterpret_cast<const std::uint32_t*>(bytes.data());
      auto* destination = static_cast<std::uint8_t*>(bottom_surface_->pixels);
      for (int y = 0; y < ScreenLayout::kBottomHeight; ++y) {
        auto* row = reinterpret_cast<std::uint32_t*>(
            destination + static_cast<std::ptrdiff_t>(y) * bottom_surface_->pitch);
        const auto* source_row =
            source + static_cast<std::ptrdiff_t>(y) * ScreenLayout::kBottomWidth;
        for (int x = 0; x < ScreenLayout::kBottomWidth; ++x) {
          row[x] = byte_swap32(source_row[x]);
        }
      }
    } else {
      conversion = SDL_ConvertPixels(
          ScreenLayout::kBottomWidth, ScreenLayout::kBottomHeight,
          SDL_PIXELFORMAT_RGBA32, bottom_canvas_->rgba_bytes().data(),
          ScreenLayout::kBottomWidth * 4, bottom_surface_->format->format,
          bottom_surface_->pixels, bottom_surface_->pitch);
    }
    if (must_lock) {
      SDL_UnlockSurface(bottom_surface_);
    }
    if (conversion == 0) {
      (void)SDL_UpdateWindowSurface(bottom_window_);
      dirty_ = false;
    }
  }

  void refresh_panel_tick(std::uint64_t frame_started) {
    const FrameScheduler::Decision decision = scheduler_.advance(frame_started);
    if (bottom_mode_ == BottomScreenMode::Panel && decision.render_bottom &&
        (dirty_ || bottom_ui_.is_pressed())) {
      // In game mode the lower screen is repainted by after_frame() instead,
      // in lockstep with the frame it mirrors.
      render_bottom();
    }

  }
