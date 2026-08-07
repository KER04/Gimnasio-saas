/**
 * Entrenamiento (RF-12): catálogo de ejercicios, rutinas y seguimiento de
 * medidas.
 *
 * No incluye el registro serie a serie ni los records personales: sus tablas
 * existen, pero se escriben "desde el celular, entre series" y en este
 * sistema el cliente no tiene acceso.
 */

export interface GrupoMuscular {
  id: number;
  nombre: string;
  orden: number;
}

export interface Ejercicio {
  id: number;
  nombre: string;
  descripcion: string | null;
  grupo_muscular: number;
  grupo_nombre: string;
  activo: boolean;
}

export interface EjercicioFormulario {
  nombre: string;
  descripcion?: string | null;
  grupo_muscular: number;
  activo?: boolean;
}

/**
 * Un ejercicio dentro de un día. `peso_kg` es lo PLANIFICADO por el
 * entrenador, no lo que el cliente levantó.
 *
 * Se mide por repeticiones O por tiempo, nunca por las dos: press banca va en
 * repeticiones y correr en minutos. La base lo impone con `ck_rutejer_medida`.
 */
export interface RutinaEjercicio {
  id?: number;
  ejercicio: number;
  ejercicio_nombre?: string;
  grupo_nombre?: string;
  orden: number;
  series: number;
  /** `null` si el ejercicio va por tiempo. */
  repeticiones: number | null;
  /** `null` si el ejercicio va por repeticiones. */
  duracion_minutos: number | null;
  peso_kg: string | null;
  /** Se guarda en SEGUNDOS (así es la columna), pero la pantalla trabaja en
   * minutos: nadie prescribe "90 segundos de descanso", dice "minuto y
   * medio". */
  descanso_segundos: number | null;
  notas: string | null;
}

export interface RutinaDia {
  id?: number;
  numero: number;
  nombre: string;
  ejercicios: RutinaEjercicio[];
}

export interface Rutina {
  id: number;
  cliente: number;
  cliente_nombre: string;
  entrenador: number;
  entrenador_nombre: string;
  nombre: string;
  objetivo: string | null;
  fecha_inicio: string;
  fecha_fin: string | null;
  activa: boolean;
  dias: RutinaDia[];
  creado_en: string;
}

/** La rutina se manda ENTERA: es un documento, no filas sueltas. Si se
 * incluyen `dias`, sustituyen a los que hubiera. */
export interface RutinaFormulario {
  cliente: number;
  nombre: string;
  objetivo?: string | null;
  fecha_inicio?: string;
  fecha_fin?: string | null;
  dias?: RutinaDia[];
}

/** Las 13 medidas del formulario, en el orden en que se toman. */
export const MEDIDAS = [
  'peso_kg', 'cuello', 'hombros', 'pecho_espalda', 'brazos', 'antebrazos',
  'muneca', 'abdomen', 'cintura', 'cadera_gluteos', 'piernas_media',
  'rodillas_arriba', 'pantorrillas', 'tobillos',
] as const;

export type Medida = (typeof MEDIDAS)[number];

export const ETIQUETAS_MEDIDA: Record<Medida, string> = {
  peso_kg: 'Peso (kg)',
  cuello: 'Cuello',
  hombros: 'Hombros',
  pecho_espalda: 'Pecho / espalda',
  brazos: 'Brazos',
  antebrazos: 'Antebrazos',
  muneca: 'Muñeca',
  abdomen: 'Abdomen',
  cintura: 'Cintura',
  cadera_gluteos: 'Cadera / glúteos',
  piernas_media: 'Piernas (media)',
  rodillas_arriba: 'Rodillas (arriba)',
  pantorrillas: 'Pantorrillas',
  tobillos: 'Tobillos',
};

export type ControlMedida = {
  id: number;
  numero_control: number;
  fecha: string;
  edad: number | null;
  registrado_por: number;
  registrado_por_nombre: string;
  creado_en: string;
} & Record<Medida, string | null>;

export interface FichaMedidas {
  id: number;
  cliente: number;
  cliente_nombre: string;
  entrenador: number;
  entrenador_nombre: string;
  modalidad: string | null;
  fecha_inicio: string;
  /** En CENTÍMETROS. El error más común es escribir metros. */
  estatura_cm: string | null;
  whatsapp: string | null;
  activa: boolean;
  controles: ControlMedida[];
  creado_en: string;
}

export interface FichaFormulario {
  cliente: number;
  modalidad?: string | null;
  estatura_cm?: string | null;
  whatsapp?: string | null;
}

/** Una medida a lo largo de todos los controles, con su evolución. */
export interface FilaComparativa {
  medida: Medida;
  /** Un valor por control, en orden. `null` donde no se tomó. */
  valores: (string | null)[];
  /** Entre el primero y el último NO NULOS. `null` con menos de dos tomas. */
  diferencia: string | null;
}

export interface Comparativa {
  ficha: { id: number; cliente_nombre: string; estatura_cm: string | null };
  controles: { id: number; numero_control: number; fecha: string; edad: number | null }[];
  filas: FilaComparativa[];
}
