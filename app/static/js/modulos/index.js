/* Registro dos módulos — o ÚNICO lugar que enumera módulos.
 *
 * O núcleo (main.js, cockpit.js, regua.js, personalizar.js) não cita nenhum
 * módulo pelo nome. Acrescentar módulo é: criar o arquivo e importá-lo aqui.
 * É o teste de aberto/fechado do doc 10 §4.
 *
 * 13 do protótipo completo + 5 que existiam como tela e não têm contrapartida
 * lá. `projetos` entrou nessa lista numa segunda passada: é a tela de start/stop
 * de stack compose, atrás de `require_unlock`, e foi ela que obrigou a F5 a
 * existir — some no porte se ninguém a registrar. Decisão de escopo registrada no doc 14: os extras são registrados
 * (nada se perde) mas ficam fora de qualquer preset padrão — `reconciliar`
 * acrescenta módulo desconhecido como oculto, então eles só entram na grade se
 * o operador pedir no Personalizar. Nenhum deles tem chave no summary, logo
 * nenhum aparece na régua: chip sem fonte seria dado inventado.
 */

import { registrar } from '../kernel/registry.js';

// --- os 13 do protótipo ---------------------------------------------------
import armazenamento from './armazenamento.js';
import atencao from './atencao.js';
import auditoria from './auditoria.js';
import capacidade from './capacidade.js';
import config from './config.js';
import containers from './containers.js';
import drift from './drift.js';
import eventos from './eventos.js';
import ingress from './ingress.js';
import logs from './logs.js';
import metricas from './metricas.js';
import stacks from './stacks.js';
import tarefas from './tarefas.js';

// --- os 5 fora dos presets ------------------------------------------------
import backend from './backend.js';
import executivo from './executivo.js';
import plantao from './plantao.js';
import projetos from './projetos.js';
import topologia from './topologia.js';

export const DO_PROTOTIPO = [
  armazenamento, atencao, auditoria, capacidade, config, containers,
  drift, eventos, ingress, logs, metricas, stacks, tarefas,
];

export const EXTRAS = [backend, executivo, plantao, projetos, topologia];

export function registrarTodos() {
  for (const mod of [...DO_PROTOTIPO, ...EXTRAS]) registrar(mod);
}
