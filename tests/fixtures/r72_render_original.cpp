void getScaleRect(const SDL_Rect* rect, double scale_factor,
                  SDL_FRect* dst_rect) {
#if SDL_VERSION_ATLEAST(2, 0, 10)
  // If using SDL 2.0.10 or newer, we can use floats to get better precision
  // on scaled rendering.
  dst_rect->x = static_cast<float>(rect->x * scale_factor) - frect_overdraw;
  dst_rect->y = static_cast<float>(rect->y * scale_factor) - frect_overdraw;
  dst_rect->w = static_cast<float>(rect->w * scale_factor) + 2 * frect_overdraw;
  dst_rect->h = static_cast<float>(rect->h * scale_factor) + 2 * frect_overdraw;
#else
  // Prior to SDL 2.0.10, fallback to using the enclosing integer SDL_Rect for
  // scaled rendering.
  getEnclosingScaleRect(rect, scale_factor, dst_rect);
#endif
}
void render_target::draw(SDL_Texture* pTexture, const SDL_Rect* prcSrcRect,
                         const SDL_Rect* prcDstRect, int iFlags) {
#ifdef CORSIXTH_3DS_GPU
  cth3ds::GpuSubmitBridgeScope submit_bridge;
#endif
#ifdef CORSIXTH_3DS
  ++cth3ds::render_work.draws;
  if (iFlags & (thdf_flip_horizontal | thdf_flip_vertical)) ++cth3ds::render_work.flipped_fallback;
#endif
  SDL_SetTextureAlphaMod(pTexture, 0xFF);
  if (iFlags & thdf_alpha_50) {
    SDL_SetTextureAlphaMod(pTexture, 0x80);
  } else if (iFlags & thdf_alpha_75) {
    SDL_SetTextureAlphaMod(pTexture, 0x40);
  }

  int iSDLFlip = SDL_FLIP_NONE;
  if (iFlags & thdf_flip_horizontal) iSDLFlip |= SDL_FLIP_HORIZONTAL;
  if (iFlags & thdf_flip_vertical) iSDLFlip |= SDL_FLIP_VERTICAL;

  SDL_FRect scaledDstRect;
  getScaleRect(prcDstRect, draw_scale(), &scaledDstRect);
  if (current_target) current_target->offset(scaledDstRect);
#ifdef CORSIXTH_3DS
  if (cth3ds::blit_draw(renderer, game_surface, pTexture, prcSrcRect, &scaledDstRect,
                        static_cast<SDL_RendererFlip>(iSDLFlip)) != 0)
    throw std::runtime_error(SDL_GetError());
  return;
#endif
  if (iSDLFlip != 0) {
    // iSDLFlip may be 3 (HORIZONTAL | VERTICAL) but there is no enum value for
    // that
    SDL_RenderCopyExF(renderer, pTexture, prcSrcRect, &scaledDstRect, 0,
                      nullptr,
                      (SDL_RendererFlip)iSDLFlip);  // NOLINT
  } else {
    SDL_RenderCopyF(renderer, pTexture, prcSrcRect, &scaledDstRect);
  }
}
