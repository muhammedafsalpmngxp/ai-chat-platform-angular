import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth.guards';

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [guestGuard],
    title: 'Log in · AI Chatbot',
    loadComponent: () => import('./pages/login/login').then((m) => m.Login),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./layout/shell/shell').then((m) => m.Shell),
    children: [
      {
        path: '',
        title: 'AI Chatbot',
        loadComponent: () => import('./pages/chat/chat-page').then((m) => m.ChatPage),
      },
      {
        path: 'settings',
        title: 'Settings · AI Chatbot',
        loadComponent: () => import('./pages/settings/settings').then((m) => m.Settings),
      },
      {
        path: 'c/:id',
        title: 'AI Chatbot',
        loadComponent: () => import('./pages/chat/chat-page').then((m) => m.ChatPage),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
