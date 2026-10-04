
    import { appendFileSync } from "node:fs";
    export async function load(url, context, nextLoad) {
      if (/chatgpt-(?:account-pool|profile-switch)\.mjs$/.test(url)) {
        appendFileSync(process.env.IMPORT_LOG, url + "\n");
      }
      return nextLoad(url, context);
    }
  