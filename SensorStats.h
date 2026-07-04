#ifndef SENSOR_STATS_H
#define SENSOR_STATS_H

#include <stdint.h>

struct LightReadStats {
  uint16_t average[5] = {0, 0, 0, 0, 0};
  uint16_t minValue[5] = {0, 0, 0, 0, 0};
  uint16_t maxValue[5] = {0, 0, 0, 0, 0};
  uint16_t range[5] = {0, 0, 0, 0, 0};
};

struct PressureReadStats {
  int32_t averageRaw = 0;
  int32_t minRaw = 0;
  int32_t maxRaw = 0;
  int32_t rangeRaw = 0;
  int32_t trimmedMinRaw = 0;
  int32_t trimmedMaxRaw = 0;
  int32_t trimmedRangeRaw = 0;
  int validCount = 0;
  int failCount = 0;
  bool trimmed = false;
};

#endif
