const CACHE_NAME = 'cockpit-v4';
const STATIC_ASSETS = [
  '/static/index.html',
  '/static/css/base.css',
  '/static/css/themes.css',
  '/static/css/components.css',
  '/static/css/fontes.css',
  // A IMAGEM serve o bundle (ver app/Dockerfile); o repositório serve os módulos.
  // Os dois entram na lista: `cache.add` tem catch por URL, então o que não existir
  // naquele ambiente falha sozinho, sem derrubar a instalação do service worker.
  '/static/js/main.bundle.js',
  '/static/js/fmt.js',
  '/static/js/store.js',
  '/static/js/data.js',
  '/static/js/notifications.js',
  '/static/js/commands.js',
  '/static/js/main.js',
  // Divida registrada no doc 14 e paga aqui: sem o kernel, os modulos e as
  // telas no cache, o service worker servia um main.js que importa arquivos
  // que ele nao tem — offline a interface ficava em branco sem erro visivel.
  '/static/js/kernel/app.js',
  '/static/js/kernel/cockpit.js',
  '/static/js/kernel/escopo.js',
  '/static/js/kernel/layout.js',
  '/static/js/kernel/personalizar.js',
  '/static/js/kernel/presets.js',
  '/static/js/kernel/registry.js',
  '/static/js/kernel/regua.js',
  '/static/js/kernel/subtela.js',
  '/static/js/modulos/armazenamento.js',
  '/static/js/modulos/atencao.js',
  '/static/js/modulos/auditoria.js',
  '/static/js/modulos/backend.js',
  '/static/js/modulos/capacidade.js',
  '/static/js/modulos/config.js',
  '/static/js/modulos/containers.js',
  '/static/js/modulos/drift.js',
  '/static/js/modulos/eventos.js',
  '/static/js/modulos/executivo.js',
  '/static/js/modulos/index.js',
  '/static/js/modulos/ingress.js',
  '/static/js/modulos/logs.js',
  '/static/js/modulos/metricas.js',
  '/static/js/modulos/plantao.js',
  '/static/js/modulos/projetos.js',
  '/static/js/modulos/stacks.js',
  '/static/js/modulos/tarefas.js',
  '/static/js/modulos/topologia.js',
  '/static/js/screens/attention.js',
  '/static/js/screens/auditoria.js',
  '/static/js/screens/backend.js',
  '/static/js/screens/capacidade.js',
  '/static/js/screens/executivo.js',
  '/static/js/screens/ingress.js',
  '/static/js/screens/plantao.js',
  '/static/js/screens/projects.js',
  '/static/js/screens/tarefas.js',
  '/static/js/screens/topologia.js',
  '/static/manifest.json',
  '/static/assets/icon.svg',
  // Fontes auto-hospedadas: sem elas no cache, offline cai para a fonte do sistema.
  '/static/assets/fonts/inter-latin.woff2',
  '/static/assets/fonts/inter-latin-ext.woff2',
  '/static/assets/fonts/jetbrains-mono-latin.woff2',
  '/static/assets/fonts/jetbrains-mono-latin-ext.woff2',
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      Promise.allSettled(STATIC_ASSETS.map((url) =>
        cache.add(url).catch(() => {})
      ))
    )
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});
