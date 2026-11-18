#pragma once
#include <vector>

namespace detroit::adaptive {
struct Size { double width, height; };
struct Point { double x, y; };
struct Rect { double x, y, width, height; };
// A single scale is intentional: this API cannot express non-uniform stretching.
struct Transform {
    double scale;
    Point offset;
    Point to_screen(Point local) const;
    Point to_local(Point screen) const;
};
enum class MediaKind { StillImage, PrerecordedVideo };
struct MediaPlacement { Transform transform; Rect source_uv; Rect destination; };
struct Projection { double horizontal_fov, vertical_fov, x_scale, y_scale; };

// Preserve BOTH reference FOVs: expand the other axis for narrower/wider screens.
Projection expand_projection(double reference_vertical_fov, double reference_aspect, Size target);
// Whole-image fit. Empty area belongs to the responsive scene/background, not a matte.
Transform contain(Size source, Rect destination);
// Crop is only legal for prerecorded video; still-image crop requests are rejected.
MediaPlacement place_media(Size source, Rect destination, MediaKind kind, bool crop);
// Edge anchors reposition a whole component without changing its shape.
Rect anchor_component(Size original, Rect destination, Point anchor, Point inset, double scale);
// Reflow complete menu components into rows, retaining their individual proportions.
std::vector<Rect> flow_components(const std::vector<Size>& items, Rect destination,
                                  double preferred_scale, double gap);
bool contains(Rect outer, Rect inner, double tolerance=1e-8);
}
