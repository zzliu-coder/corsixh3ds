#pragma once

// Direct/native builds default to the production loose-file implementation.
#ifndef CTH3DS_RESOURCE_EXPERIMENT
#define CTH3DS_RESOURCE_EXPERIMENT 0
#endif
#if CTH3DS_RESOURCE_EXPERIMENT != 0 && CTH3DS_RESOURCE_EXPERIMENT != 1
#error "CTH3DS_RESOURCE_EXPERIMENT must be 0 or 1"
#endif
