import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'board' },
  {
    path: 'board',
    loadComponent: () => import('./features/board/board.component').then((m) => m.BoardComponent),
  },
  {
    path: 'crew',
    loadComponent: () => import('./features/crew/crew.component').then((m) => m.CrewComponent),
  },
  {
    path: 'crew/:id',
    loadComponent: () => import('./features/crew/crew.component').then((m) => m.CrewComponent),
  },
  { path: '**', redirectTo: 'board' },
];
