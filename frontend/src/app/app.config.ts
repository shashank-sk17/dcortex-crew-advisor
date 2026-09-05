import {
  ApplicationConfig, inject, provideAppInitializer, provideZoneChangeDetection,
} from '@angular/core';
import { provideHttpClient, withFetch } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { environment } from '../environments/environment';
import { API } from './core/api.port';
import { HttpApiService } from './core/http-api.service';
import { MockApiService } from './core/mock/mock-api.service';
import { Dataset } from './core/mock/dataset';
import { routes } from './app.routes';
import { loadRuntimeConfig } from './core/runtime-config';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideHttpClient(withFetch()),
    provideRouter(routes),

    // The one swap point: mock (dataset in-app) vs real REST.
    { provide: API, useClass: environment.useMock ? MockApiService : HttpApiService },

    // Resolve the backend URLs from /config.json, then load the bundled dataset
    // if we're in mock mode. `inject()` has to run synchronously inside the
    // injection context, so the Dataset is captured before the first await.
    provideAppInitializer(() => {
      const dataset = environment.useMock ? inject(Dataset) : null;
      return loadRuntimeConfig().then(() => dataset?.load());
    }),
  ],
};
