export const environment = {
  production: false,
  /**
   * The entire mock -> real integration step.
   * true  = scripted MockAdvisorService (works with zero backend)
   * false = real REST (Gayathri's api/) + real advisor (Shashank's agent/, via devui.server)
   */
  useMock: false,
  /** The REST view layer — board/sidebar/crew/alerts. Gayathri's Flask app, `python -m api.app`. */
  apiBase: 'http://127.0.0.1:5000',
  /**
   * The advisor — chat + accept/modify. Separate process from apiBase until
   * `/ask` lands in api/app.py (issue #32); today this is Shashank's dev
   * console: `AGENT_DATA=fixtures python -m devui.server` on :8420 (no DB,
   * no API key needed — deterministic answer-key fixtures).
   */
  advisorBase: 'http://localhost:8420',
};
