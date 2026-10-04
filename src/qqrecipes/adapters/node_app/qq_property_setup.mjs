// Run by the node-app adapter before vitest (V0-REC-04), in the app directory. It makes fast-check
// property tests deterministic and time-boxed in the gate without the repo changing anything:
// it writes .qq/qq-fast-check.mjs (a vitest setup file that configures fast-check globally) and
// .qq/vitest.config.mjs, which wraps the repo's own vitest config, if any, and adds that setup file.
// Environment overrides: QQ_PROPERTY_SEED (default 42), QQ_PROPERTY_EXAMPLES (default 100),
// QQ_PROPERTY_TIME_LIMIT_MS per property (default 5000).
import { existsSync, mkdirSync, writeFileSync } from "node:fs";

const SETUP = `import fc from "fast-check";
const num = (key, fallback) => {
  const v = Number(process.env[key]);
  return Number.isFinite(v) && v > 0 ? v : fallback;
};
fc.configureGlobal({
  seed: num("QQ_PROPERTY_SEED", 42),
  numRuns: num("QQ_PROPERTY_EXAMPLES", 100),
  interruptAfterTimeLimit: num("QQ_PROPERTY_TIME_LIMIT_MS", 5000),
  markInterruptAsFailure: false,
});
`;

const base = ["vitest.config.ts", "vitest.config.mts", "vitest.config.js", "vitest.config.mjs",
  "vite.config.ts", "vite.config.mts", "vite.config.js", "vite.config.mjs"].find((f) => existsSync(f));

// TODO(expert): a base config that exports a function (defineConfig(() => ...)) is not merged.
const config = `import { configDefaults, defineConfig, mergeConfig } from "vitest/config";
${base ? `import base from "../${base}";` : "const base = {};"}
export default mergeConfig(base, defineConfig({
  root: ${JSON.stringify(process.cwd())},
  test: {
    setupFiles: ["./.qq/qq-fast-check.mjs"],
    exclude: [...(base.test?.exclude ?? configDefaults.exclude), "**/.qq/**", "**/.next/**"],
  },
}));
`;

mkdirSync(".qq", { recursive: true });
writeFileSync(".qq/qq-fast-check.mjs", SETUP);
writeFileSync(".qq/vitest.config.mjs", config);
console.log(`qq: fast-check gate settings written${base ? `, wrapping ${base}` : ""}`);
