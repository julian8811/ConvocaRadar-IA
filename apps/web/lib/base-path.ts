export const PUBLIC_BASE_PATH = "/observatorio";

export function withBasePath(path: string): string {
  if (!path.startsWith("/")) return path;
  if (path === PUBLIC_BASE_PATH || path.startsWith(`${PUBLIC_BASE_PATH}/`)) {
    return path;
  }
  return `${PUBLIC_BASE_PATH}${path}`;
}
