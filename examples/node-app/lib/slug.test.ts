// Property tests (V0-REC-04): fast-check runs inside vitest as ordinary tests.
import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { slugify } from "./slug";

describe("slugify", () => {
  it("always gives a safe, bounded slug", () => {
    fc.assert(
      fc.property(fc.string({ unit: "binary" }), (title) => {
        const slug = slugify(title);
        expect(slug).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
        expect(slug.length).toBeLessThanOrEqual(60);
      }),
    );
  });

  it("is idempotent", () => {
    fc.assert(fc.property(fc.string(), (title) => slugify(slugify(title)) === slugify(title)));
  });

  it("keeps plain words", () => {
    expect(slugify("Hello World")).toBe("hello-world");
  });
});
