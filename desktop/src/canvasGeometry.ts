export type Point = [number, number];
export type PixelBox = [number, number, number, number];
export interface Transform {
  scale: number;
  x: number;
  y: number;
}
export const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));
export function imageTransform(
  width: number,
  height: number,
  viewWidth: number,
  viewHeight: number,
  zoom: number,
  pan: Point,
): Transform {
  const scale = zoom / 100;
  return {
    scale,
    x: (viewWidth - width * scale) / 2 + pan[0] * scale,
    y: (viewHeight - height * scale) / 2 + pan[1] * scale,
  };
}
export function toImage(point: Point, transform: Transform): Point {
  return [
    (point[0] - transform.x) / transform.scale,
    (point[1] - transform.y) / transform.scale,
  ];
}
export function toScreen(point: Point, transform: Transform): Point {
  return [
    point[0] * transform.scale + transform.x,
    point[1] * transform.scale + transform.y,
  ];
}
export function fitZoom(
  width: number,
  height: number,
  viewWidth: number,
  viewHeight: number,
): number {
  return Math.max(
    1,
    Math.min(
      100,
      Math.floor(
        Math.min((viewWidth - 24) / width, (viewHeight - 24) / height) * 100,
      ),
    ),
  );
}
export function boxFromPoints(
  start: Point,
  end: Point,
  width: number,
  height: number,
): PixelBox {
  const x = clamp(Math.round(Math.min(start[0], end[0])), 0, width - 1);
  const y = clamp(Math.round(Math.min(start[1], end[1])), 0, height - 1);
  return [
    x,
    y,
    Math.max(
      1,
      clamp(Math.round(Math.max(start[0], end[0])), x + 1, width) - x,
    ),
    Math.max(
      1,
      clamp(Math.round(Math.max(start[1], end[1])), y + 1, height) - y,
    ),
  ];
}
