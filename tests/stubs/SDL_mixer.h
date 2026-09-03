#pragma once
inline void Mix_Pause(int) {}
inline void Mix_PauseMusic() {}
inline void Mix_Resume(int) {}
inline void Mix_ResumeMusic() {}
inline void Mix_HaltMusic() {}
inline int Mix_HaltChannel(int) { return 0; }
