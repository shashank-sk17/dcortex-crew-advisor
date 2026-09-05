import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { environment } from '../../environments/environment';
import { AppState } from '../core/app-state';
import { SidebarComponent } from '../features/sidebar/sidebar.component';
import { AlertsPanelComponent } from '../features/alerts/alerts-panel.component';
import { ChatBubbleComponent } from '../features/advisor/chat-bubble.component';
import { IconComponent } from '../components/icon.component';

/**
 * Root cockpit frame — topbar (nav + working-date picker + MOCK/LIVE badge),
 * three columns (sidebar · routed view · alerts), and the floating advisor bubble.
 * Both rails collapse to a slim edge tab so the controller can give the main
 * display the full width when neither the shift summary nor the alert queue
 * needs to be on screen. Why: one place owns the layout and kicks off AppState
 * so every view shares a date.
 */
@Component({
  selector: 'app-cockpit',
  standalone: true,
  imports: [IconComponent, 
    RouterOutlet, RouterLink, RouterLinkActive,
    SidebarComponent, AlertsPanelComponent, ChatBubbleComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './cockpit.component.html',
  styleUrl: './cockpit.component.scss',
})
export class CockpitComponent implements OnInit {
  readonly state = inject(AppState);
  readonly mock = environment.useMock;
  readonly leftOpen = signal(true);
  readonly rightOpen = signal(true);

  ngOnInit(): void {
    this.state.init();
  }

  toggleLeft(): void {
    this.leftOpen.update((v) => !v);
  }
  toggleRight(): void {
    this.rightOpen.update((v) => !v);
  }
}
