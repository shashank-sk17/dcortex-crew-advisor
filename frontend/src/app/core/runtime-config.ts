import { environment } from '../../environments/environment';

/**
 * Backend URLs resolved at runtime, not baked into the bundle.
 *
 * The console is built once and served from a CDN, but the API and advisor it
 * talks to move — localhost during development, a hosted URL once they are
 * deployed, a different one per environment. Reading them from `/config.json`
 * beside the bundle means repointing is editing one small file, not rebuilding
 * and redeploying the whole app.
 *
 * Only the URLs are runtime-settable. `useMock` is not: it decides which class
 * is bound to the `API` token while the injector is being configured, which
 * happens before any initializer can run.
 */
export interface RuntimeConfig {
  apiBase?: string;
  advisorBase?: string;
}

/**
 * Fetched before the first view renders. A missing or malformed file is not an
 * error — it means "use what was compiled in", which is exactly right for local
 * development, so this never blocks startup.
 */
export async function loadRuntimeConfig(): Promise<void> {
  try {
    const res = await fetch('config.json', { cache: 'no-store' });
    if (!res.ok) return;
    const cfg = (await res.json()) as RuntimeConfig;
    if (typeof cfg?.apiBase === 'string') environment.apiBase = cfg.apiBase;
    if (typeof cfg?.advisorBase === 'string') {
      (environment as RuntimeConfig).advisorBase = cfg.advisorBase;
    }
  } catch {
    // offline, absent, or not JSON — keep the compiled-in defaults
  }
}
