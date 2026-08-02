import { Component, inject } from '@angular/core';

import { AuthService } from '../../core/services/auth.service';

/** Pie discreto: copyright con el nombre del gimnasio y el año actual. */
@Component({
  selector: 'app-footer',
  standalone: true,
  imports: [],
  templateUrl: './footer.html',
})
export class Footer {
  protected readonly authService = inject(AuthService);
  protected readonly anio = new Date().getFullYear();
}
