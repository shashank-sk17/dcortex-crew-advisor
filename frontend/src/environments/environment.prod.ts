export const environment = {
  production: true,
  /**
   * Self-contained until the REST API and advisor are hosted publicly.
   * MockApiService computes the board, crew, alerts and sidebar from the
   * dataset bundled in src/assets/data, and MockAdvisorService serves the
   * scripted fixtures — so a static deploy works with no backend at all.
   *
   * To go live against the real services: set this to false and put their
   * URLs in `config.json` (below). Nothing else changes.
   */
  useMock: true,
  /**
   * Left empty deliberately. Both URLs are supplied at runtime from
   * `/config.json` (see core/runtime-config.ts), so a deployed build can be
   * repointed at a different API or advisor by editing one file on the CDN —
   * no rebuild, no redeploy.
   */
  apiBase: '',
  advisorBase: '',
};
