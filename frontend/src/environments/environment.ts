export const environment = {
  production: false,
  /**
   * The entire mock -> real integration step.
   * true  = scripted MockAdvisorService (works with zero backend)
   * false = POST /api/v1/ask against api/mock.py (or the real api/app.py) via the dev-server proxy
   */
  useMock: true,
  /** Empty = same origin; the dev server proxies /api to :5000 (see proxy.conf.json). */
  apiBase: '',
};
