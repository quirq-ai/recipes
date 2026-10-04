import { slugify } from "../lib/slug";

export default function Page() {
  return <main>{slugify("Hello from quirq infra")}</main>;
}
