import { slugify } from "../../../lib/slug";

export function GET(request: Request) {
  const title = new URL(request.url).searchParams.get("title") ?? "";
  return Response.json({ slug: slugify(title) });
}
