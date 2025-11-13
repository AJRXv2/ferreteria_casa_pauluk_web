document.addEventListener('DOMContentLoaded', () => {
  // Inicializar carruseles para que avancen solos
  if (window.bootstrap && document.querySelector('.carousel')) {
    document.querySelectorAll('.carousel').forEach(el => {
      // Intervalo 4s, pausa al pasar el mouse, soporte táctil y teclado
      new bootstrap.Carousel(el, {
        interval: 4000,
        ride: 'carousel',
        pause: 'hover',
        touch: true,
        keyboard: true,
        wrap: true,
      });
    });
  }

  // Soporte para submenús en móviles: tocar el padre abre/cierra el submenú
  document.querySelectorAll('.dropdown-submenu > a.dropdown-toggle').forEach(link => {
    link.addEventListener('click', (ev) => {
      // Si es dispositivo táctil o viewport pequeño, evitamos navegar y togglamos
      const isTouch = matchMedia('(hover: none)').matches || window.innerWidth < 992;
      if (isTouch) {
        ev.preventDefault();
        ev.stopPropagation();
        const submenu = link.parentElement;
        const menu = submenu.querySelector('.dropdown-menu');
        // Cerrar otros submenús hermanos
        submenu.parentElement.querySelectorAll('.dropdown-menu.show').forEach(m => {
          if (m !== menu) m.classList.remove('show');
        });
        menu.classList.toggle('show');
      }
    });
  });

  // Cerrar submenús al cerrar el dropdown principal
  document.querySelectorAll('.dropdown').forEach(dd => {
    dd.addEventListener('hide.bs.dropdown', () => {
      dd.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
    });
  });

  // Scroller de últimos productos
  const scroller = document.getElementById('latestScroller');
  const prevBtn = document.getElementById('latestPrev');
  const nextBtn = document.getElementById('latestNext');
  if (scroller && prevBtn && nextBtn) {
    const scrollByAmount = () => Math.max(240, Math.floor(scroller.clientWidth * 0.9));
    prevBtn.addEventListener('click', () => {
      scroller.scrollBy({ left: -scrollByAmount(), behavior: 'smooth' });
    });
    nextBtn.addEventListener('click', () => {
      scroller.scrollBy({ left: scrollByAmount(), behavior: 'smooth' });
    });

    // Auto-scroll suave con pausa al pasar el mouse
    const canScroll = () => scroller.scrollWidth > scroller.clientWidth + 8;
    let autoTimer = null;
    const INTERVAL_MS = 3500;
    const doStep = () => {
      if (!canScroll()) return; // nada que mover
      const atEnd = Math.ceil(scroller.scrollLeft + scroller.clientWidth + 4) >= scroller.scrollWidth;
      if (atEnd) {
        scroller.scrollTo({ left: 0, behavior: 'smooth' });
      } else {
        scroller.scrollBy({ left: scrollByAmount(), behavior: 'smooth' });
      }
    };
    const startAuto = () => {
      if (autoTimer || !canScroll()) return;
      autoTimer = setInterval(doStep, INTERVAL_MS);
    };
    const stopAuto = () => {
      if (autoTimer) {
        clearInterval(autoTimer);
        autoTimer = null;
      }
    };

    // Pausa por interacción del usuario
    scroller.addEventListener('mouseenter', stopAuto);
    scroller.addEventListener('mouseleave', startAuto);
    scroller.addEventListener('touchstart', stopAuto, { passive: true });
    scroller.addEventListener('pointerdown', stopAuto);
    prevBtn.addEventListener('click', () => { stopAuto(); setTimeout(startAuto, INTERVAL_MS * 2); });
    nextBtn.addEventListener('click', () => { stopAuto(); setTimeout(startAuto, INTERVAL_MS * 2); });

    // Pausa cuando la pestaña no está visible
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stopAuto(); else startAuto();
    });

    // Iniciar si corresponde
    startAuto();
  }

  // Registrar productos vistos (al hacer click en una card con data-product-id)
  document.body.addEventListener('click', (e) => {
    const card = e.target.closest('[data-product-id]');
    if (!card) return;
    const pid = card.getAttribute('data-product-id');
    if (!pid) return;
    try {
      const KEY = 'recent_products_v1';
      let arr = JSON.parse(localStorage.getItem(KEY) || '[]');
      arr = arr.filter(id => id !== pid); // quitar duplicados
      arr.unshift(pid); // agregar al inicio
      if (arr.length > 20) arr = arr.slice(0,20);
      localStorage.setItem(KEY, JSON.stringify(arr));
    } catch(_) {}
  });

  // Renderizar sección de recientemente vistos si existe contenedor
  const recentContainer = document.getElementById('recentlyViewed');
  if (recentContainer) {
    try {
      const KEY = 'recent_products_v1';
      const ids = JSON.parse(localStorage.getItem(KEY) || '[]');
      if (ids.length) {
        fetch(`/api/products?ids=${ids.join(',')}`)
          .then(r => r.json())
          .then(data => {
            const wrap = document.createElement('div');
            wrap.className = 'recently-viewed-wrapper';
            data.items.forEach(p => {
              const a = document.createElement('a');
              a.href = '#'; // no hay página detalle todavía
              a.className = 'recently-viewed-item text-decoration-none';
              a.setAttribute('data-product-id', p.id);
              a.innerHTML = `
                <img src="/static/img/products/${p.image || ''}" alt="${p.name}" onerror="this.src='https://via.placeholder.com/140x90?text=No+Img'">
                <div class="mt-1 text-truncate" title="${p.name}">${p.name}</div>
              `;
              wrap.appendChild(a);
            });
            recentContainer.appendChild(wrap);
          })
          .catch(()=>{});
      } else {
        recentContainer.innerHTML = '<p class="text-muted small">Todavía no viste productos.</p>';
      }
    } catch(_) {}
  }
});
