import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { Aside } from '../aside/aside';
import { Footer } from '../footer/footer';
import { Header } from '../header/header';

/**
 * Composición visual de las pantallas autenticadas: header + aside +
 * contenido + footer. Es exactamente lo que antes vivía en `app.html`; se
 * movió aquí para que el login (y cualquier otra ruta pública) pueda
 * renderizarse sin este marco.
 */
@Component({
  selector: 'app-layout-principal',
  imports: [RouterOutlet, Header, Aside, Footer],
  templateUrl: './layout-principal.html',
  styleUrl: './layout-principal.css',
})
export class LayoutPrincipal {}
