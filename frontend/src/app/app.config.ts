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

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideHttpClient(withFetch()),
    provideRouter(routes),

    // The one swap point: mock (dataset in-app) vs real REST.
    { provide: API, useClass: environment.useMock ? MockApiService : HttpApiService },

    // Load the bundled dataset before the app renders (mock mode only).
    provideAppInitializer(() => {
      if (!environment.useMock) return Promise.resolve();
      return inject(Dataset).load();
    }),
  ],
};
