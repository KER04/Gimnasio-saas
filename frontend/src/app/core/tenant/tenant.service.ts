import { Injectable, computed, signal } from '@angular/core';

import { subdominioDesdeHostname } from './subdominio.util';

const SUBDOMINIO_RECORDADO = 'gimnasio_subdominio';

/**
 * Sabe a qué gimnasio pertenece esta sesión del navegador.
 *
 * El backend acepta el gimnasio de dos formas: por el subdominio del `Host`
 * o como campo `subdominio` en el cuerpo del login. Este servicio decide cuál
 * usar y se lo da hecho a quien construya la petición.
 *
 * Nada de esto es seguridad. Quién eres lo decide el backend al validar la
 * contraseña, y a partir de ahí el gimnasio viaja firmado dentro del JWT.
 * Esto solo sirve para no preguntarle al usuario algo que ya se puede saber.
 */
@Injectable({ providedIn: 'root' })
export class TenantService {
  /** Deducido de la URL. En producción siempre lo hay; en `localhost`, no. */
  private readonly deLaUrl = subdominioDesdeHostname(window.location.hostname);

  /** El que el usuario escribió a mano, recordado entre recargas. */
  private readonly escritoAMano = signal<string | null>(this.leerRecordado());

  /**
   * El subdominio efectivo. La URL manda sobre lo recordado: si estás en
   * `gimx.miapp.com`, el gimnasio es `gimx` aunque el navegador recuerde otro
   * de una sesión anterior.
   */
  readonly subdominio = computed<string | null>(() => this.deLaUrl ?? this.escritoAMano());

  /**
   * `true` cuando el gimnasio viene de la URL. El formulario de login usa esto
   * para decidir si mostrar el campo "código de gimnasio": si se dedujo, pedirlo
   * sería pedir algo que ya sabemos.
   */
  readonly seDeduceDeLaUrl = computed<boolean>(() => this.deLaUrl !== null);

  /** `true` si hay gimnasio por la vía que sea (URL o recordado). */
  readonly hayGimnasio = computed<boolean>(() => this.subdominio() !== null);

  /**
   * Fija el gimnasio escrito a mano y lo recuerda.
   *
   * Se recuerda a propósito: entrando por `localhost` el subdominio no se
   * puede deducir, y sin esto habría que reescribir el código en cada recarga
   * durante todo el desarrollo.
   */
  establecer(subdominio: string): void {
    const limpio = subdominio.trim().toLowerCase();
    if (!limpio) {
      return;
    }
    this.escritoAMano.set(limpio);
    try {
      localStorage.setItem(SUBDOMINIO_RECORDADO, limpio);
    } catch {
      // Modo incógnito o almacenamiento lleno: seguimos con el valor en
      // memoria. Perder la comodidad no debe romper el login.
    }
  }

  /** Olvida el gimnasio recordado. Llamar al cerrar sesión: en un mostrador
   * compartido, el siguiente en entrar no debería heredar el del anterior. */
  olvidar(): void {
    this.escritoAMano.set(null);
    try {
      localStorage.removeItem(SUBDOMINIO_RECORDADO);
    } catch {
      // Ver `establecer`.
    }
  }

  /**
   * Añade el `subdominio` al cuerpo de una petición de login o registro, si
   * hay uno y el cuerpo no traía ya el suyo.
   *
   * Se envía siempre que se conozca, incluso cuando el `Host` también lo
   * lleva: el backend solo rechaza si ambos apuntan a gimnasios DISTINTOS, y
   * mandarlo explícito hace que la petición funcione igual aunque el API viva
   * en otro host.
   */
  conSubdominio<T extends { subdominio?: string }>(cuerpo: T): T {
    if (cuerpo.subdominio) {
      return cuerpo;
    }
    const subdominio = this.subdominio();
    return subdominio ? { ...cuerpo, subdominio } : cuerpo;
  }

  private leerRecordado(): string | null {
    try {
      return localStorage.getItem(SUBDOMINIO_RECORDADO);
    } catch {
      return null;
    }
  }
}
