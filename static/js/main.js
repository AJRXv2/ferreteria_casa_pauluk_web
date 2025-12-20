function initImagePickerBoxes(scope) {
  const root = scope || document;
  root.querySelectorAll('.image-picker-box').forEach((box) => {
    if (box.dataset.pickerBound === '1') return;
    const inputId = box.getAttribute('data-input-id');
    if (!inputId) return;
    const input = document.getElementById(inputId);
    if (!input) return;
    const placeholder = box.querySelector('.image-picker-placeholder');
    const thumb = box.querySelector('.image-picker-thumb');

    function clearPreview() {
      if (thumb && thumb.dataset.objectUrl) {
        URL.revokeObjectURL(thumb.dataset.objectUrl);
        delete thumb.dataset.objectUrl;
      }
      if (thumb) {
        thumb.removeAttribute('src');
        thumb.classList.add('d-none');
      }
      if (placeholder) placeholder.classList.remove('d-none');
    }

    function showPreview(url, isObjectUrl) {
      if (!thumb || !url) {
        clearPreview();
        return;
      }
      if (thumb.dataset.objectUrl && thumb.dataset.objectUrl !== url) {
        URL.revokeObjectURL(thumb.dataset.objectUrl);
        delete thumb.dataset.objectUrl;
      }
      if (isObjectUrl) {
        thumb.dataset.objectUrl = url;
      }
      thumb.src = url;
      thumb.classList.remove('d-none');
      if (placeholder) placeholder.classList.add('d-none');
    }

    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      if (!file) {
        clearPreview();
        return;
      }
      const url = URL.createObjectURL(file);
      showPreview(url, true);
    });

    box.addEventListener('click', () => input.click());
    box.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        input.click();
      }
    });

    const existing = box.getAttribute('data-existing-src');
    if (existing) showPreview(existing, false);
    box.dataset.pickerBound = '1';
  });
}

window.initImagePickerBoxes = initImagePickerBoxes;

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
      if (e.target && e.target.dataset && e.target.dataset.allowEnter === 'true') return;
      let arr = JSON.parse(localStorage.getItem(KEY) || '[]');
      arr = arr.filter(id => id !== pid); // quitar duplicados
      arr.unshift(pid); // agregar al inicio
      if (arr.length > 20) arr = arr.slice(0,20);
      localStorage.setItem(KEY, JSON.stringify(arr));
    } catch(_) {}
    
      const productUrl = card.getAttribute('data-product-url');
      const interactive = e.target.closest('a, button, input, textarea, select, label, form');
      if (productUrl && !interactive) {
        window.location.href = productUrl;
      }
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
              a.href = `/productos/${p.id}`;
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

  const thumbButtons = document.querySelectorAll('[data-gallery-thumb]');
  const mainImage = document.getElementById('productMainImage');
  if (thumbButtons.length && mainImage) {
    thumbButtons.forEach((button, index) => {
      if (index === 0) button.classList.add('active');
      button.addEventListener('click', () => {
        const src = button.getAttribute('data-gallery-thumb');
        if (src) {
          mainImage.src = src;
        }
        thumbButtons.forEach(btn => btn.classList.remove('active'));
        button.classList.add('active');
      });
    });
  }

  initImagePickerBoxes(document);

  const galleryInput = document.querySelector('[data-gallery-input="true"]');
  const galleryPreview = document.getElementById('galleryPreview');
  if (galleryInput && galleryPreview) {
    let selectedFiles = [];
    let objectUrls = [];
    let draggingPreviewCard = null;

    const clearPreviewUrls = () => {
      objectUrls.forEach((url) => {
        try { URL.revokeObjectURL(url); } catch (_) {}
      });
      objectUrls = [];
    };

    const syncInputFiles = () => {
      try {
        const dt = new DataTransfer();
        selectedFiles.forEach((f) => dt.items.add(f));
        galleryInput.files = dt.files;
      } catch (_) {
        // Si el navegador no soporta DataTransfer asignable, queda solo el preview visual.
      }
    };

    const renderSelectedFiles = () => {
      clearPreviewUrls();
      galleryPreview.innerHTML = '';
      if (!selectedFiles.length) {
        galleryPreview.classList.add('d-none');
        return;
      }
      galleryPreview.classList.remove('d-none');

      selectedFiles.forEach((file, index) => {
        const url = URL.createObjectURL(file);
        objectUrls.push(url);

        const card = document.createElement('div');
        card.className = 'gallery-thumb-card gallery-preview-card';
        card.setAttribute('draggable', 'true');
        card.dataset.previewIndex = String(index);

        const ratio = document.createElement('div');
        ratio.className = 'ratio ratio-1x1 gallery-thumb-img-wrapper';
        const img = document.createElement('img');
        img.src = url;
        img.alt = file.name || 'Imagen seleccionada';
        img.className = 'img-fluid gallery-thumb-img';
        ratio.appendChild(img);
        card.appendChild(ratio);

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-outline-secondary btn-sm w-100';
        removeBtn.textContent = 'Quitar';
        removeBtn.addEventListener('click', () => {
          selectedFiles.splice(index, 1);
          syncInputFiles();
          renderSelectedFiles();
        });
        card.appendChild(removeBtn);

        galleryPreview.appendChild(card);
      });
    };

    const cardFromEvent = (ev) => ev && ev.target && ev.target.closest && ev.target.closest('.gallery-preview-card');

    galleryPreview.addEventListener('dragstart', (ev) => {
      const card = cardFromEvent(ev);
      if (!card) return;
      draggingPreviewCard = card;
      card.classList.add('is-dragging');
      try {
        ev.dataTransfer.effectAllowed = 'move';
      } catch (_) {}
    });

    galleryPreview.addEventListener('dragend', () => {
      if (draggingPreviewCard) draggingPreviewCard.classList.remove('is-dragging');
      draggingPreviewCard = null;
      galleryPreview.querySelectorAll('.drag-over').forEach((n) => n.classList.remove('drag-over'));
    });

    galleryPreview.addEventListener('dragover', (ev) => {
      if (!draggingPreviewCard) return;
      ev.preventDefault();
      const over = cardFromEvent(ev);
      if (!over || over === draggingPreviewCard) return;
      over.classList.add('drag-over');
    });

    galleryPreview.addEventListener('dragleave', (ev) => {
      const over = cardFromEvent(ev);
      if (!over) return;
      over.classList.remove('drag-over');
    });

    galleryPreview.addEventListener('drop', (ev) => {
      if (!draggingPreviewCard) return;
      ev.preventDefault();
      const target = cardFromEvent(ev);
      if (!target || target === draggingPreviewCard) return;

      const fromIndex = Number(draggingPreviewCard.dataset.previewIndex);
      const toIndex = Number(target.dataset.previewIndex);
      if (Number.isNaN(fromIndex) || Number.isNaN(toIndex)) return;

      const moved = selectedFiles.splice(fromIndex, 1)[0];
      selectedFiles.splice(toIndex, 0, moved);
      syncInputFiles();
      renderSelectedFiles();
    });

    galleryInput.addEventListener('change', () => {
      selectedFiles = Array.from(galleryInput.files || []);
      renderSelectedFiles();
    });
  }

  const productForm = document.getElementById('productForm');
  const uploadOverlay = document.getElementById('imageUploadOverlay');
  if (productForm && uploadOverlay) {
    productForm.addEventListener('submit', () => {
      const fileInputs = Array.from(productForm.querySelectorAll('input[type="file"]'));
      const hasFiles = fileInputs.some((input) => input.files && input.files.length);
      if (!hasFiles) return;
      uploadOverlay.classList.remove('d-none');
      uploadOverlay.classList.add('d-flex');
      productForm.querySelectorAll('.image-picker-box').forEach((box) => {
        const inputId = box.getAttribute('data-input-id');
        if (!inputId) return;
        const input = document.getElementById(inputId);
        if (!input || !input.files || !input.files.length) return;
        const indicator = box.querySelector('[data-upload-indicator]');
        if (indicator) indicator.classList.remove('d-none');
      });
    });
  }

  if (productForm) {
    const galleryEndpoint = productForm.dataset.galleryUrlEndpoint;
    const galleryContext = productForm.dataset.galleryContext;
    const galleryContextId = productForm.dataset.galleryContextId;
    const galleryReorderEndpoint = productForm.dataset.galleryReorderEndpoint;
    const galleryUrlInputs = Array.from(productForm.querySelectorAll('.gallery-url-input'));
    const galleryStatus = document.getElementById('galleryUrlStatus');
    const galleryThumbs = document.getElementById('currentGalleryThumbnails');
    const clearGalleryBtn = productForm.querySelector('[data-clear-gallery="true"]');
    const deleteProductBtn = productForm.querySelector('[data-delete-product="true"]');
    let galleryUploadInFlight = false;

    const parseRemoveTokenPayload = (token) => {
      if (!token || typeof token !== 'string') return null;
      const parts = token.split('|');
      if (parts.length < 2) return null;
      return parts.slice(1).join('|');
    };

    const persistGalleryOrder = async () => {
      if (!galleryReorderEndpoint || !galleryThumbs) return;
      const cards = Array.from(galleryThumbs.querySelectorAll('.gallery-thumb-card'));
      const order = cards
        .map((c) => c.dataset.gallerySortId)
        .filter((v) => v && v.trim().length);
      if (!order.length) return;
      try {
        await fetch(galleryReorderEndpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({ order }),
        });
      } catch (_) {
        // Silencioso: si falla, el usuario puede reintentar moviendo otra vez
      }
    };

    const enableGalleryDragSort = () => {
      if (!galleryThumbs || galleryThumbs.dataset.dragSortBound === '1') return;
      if (!galleryReorderEndpoint) return;

      let dragging = null;

      const isDraggableCard = (el) => el && el.classList && el.classList.contains('gallery-thumb-card');

      galleryThumbs.addEventListener('dragstart', (ev) => {
        const card = ev.target && ev.target.closest && ev.target.closest('.gallery-thumb-card');
        if (!isDraggableCard(card)) return;
        dragging = card;
        card.classList.add('is-dragging');
        try {
          ev.dataTransfer.effectAllowed = 'move';
          ev.dataTransfer.setData('text/plain', card.dataset.gallerySortId || '');
        } catch (_) {}
      });

      galleryThumbs.addEventListener('dragend', () => {
        if (dragging) dragging.classList.remove('is-dragging');
        dragging = null;
        galleryThumbs.querySelectorAll('.drag-over').forEach((n) => n.classList.remove('drag-over'));
      });

      galleryThumbs.addEventListener('dragover', (ev) => {
        if (!dragging) return;
        ev.preventDefault();
        const over = ev.target && ev.target.closest && ev.target.closest('.gallery-thumb-card');
        if (!isDraggableCard(over) || over === dragging) return;
        over.classList.add('drag-over');
      });

      galleryThumbs.addEventListener('dragleave', (ev) => {
        const over = ev.target && ev.target.closest && ev.target.closest('.gallery-thumb-card');
        if (!isDraggableCard(over)) return;
        over.classList.remove('drag-over');
      });

      galleryThumbs.addEventListener('drop', async (ev) => {
        if (!dragging) return;
        ev.preventDefault();
        const target = ev.target && ev.target.closest && ev.target.closest('.gallery-thumb-card');
        if (!isDraggableCard(target) || target === dragging) return;

        const rect = target.getBoundingClientRect();
        const before = ev.clientX < rect.left + rect.width / 2;
        if (before) {
          galleryThumbs.insertBefore(dragging, target);
        } else {
          galleryThumbs.insertBefore(dragging, target.nextSibling);
        }
        target.classList.remove('drag-over');
        await persistGalleryOrder();
      });

      galleryThumbs.dataset.dragSortBound = '1';
    };

    const attachRemovalConfirm = (button) => {
      if (!button || button.dataset.boundConfirm === '1') return;
      button.addEventListener('click', (ev) => {
        if (confirm('¿Eliminar esta imagen de la galería?')) return;
        ev.preventDefault();
        ev.stopPropagation();
      });
      button.dataset.boundConfirm = '1';
    };

    const attachClearConfirm = (button) => {
      if (!button || button.dataset.boundConfirm === '1') return;
      button.addEventListener('click', (ev) => {
        if (confirm('¿Eliminar todas las imágenes de la galería?')) return;
        ev.preventDefault();
        ev.stopPropagation();
      });
      button.dataset.boundConfirm = '1';
    };

    productForm.querySelectorAll('[data-gallery-remove="true"]').forEach(attachRemovalConfirm);
    attachClearConfirm(clearGalleryBtn);

    if (deleteProductBtn) {
      deleteProductBtn.addEventListener('click', (ev) => {
        if (confirm('¿Eliminar este producto? Esta acción no se puede deshacer.')) return;
        ev.preventDefault();
        ev.stopPropagation();
      });
    }

    const showGalleryStatus = (message, level = 'info') => {
      if (!galleryStatus || !message) return;
      galleryStatus.innerHTML = `<div class="alert alert-${level} py-2 mb-0">${message}</div>`;
      if (level === 'success') {
        setTimeout(() => {
          galleryStatus.innerHTML = '';
        }, 4000);
      }
    };

    const appendGalleryThumb = (thumbUrl, removeToken) => {
      if (!galleryThumbs || !thumbUrl) return;
      galleryThumbs.classList.remove('d-none');
      const card = document.createElement('div');
      card.className = 'gallery-thumb-card';
      card.setAttribute('draggable', 'true');
      const ratio = document.createElement('div');
      ratio.className = 'ratio ratio-1x1 gallery-thumb-img-wrapper';
      const img = document.createElement('img');
      img.src = thumbUrl;
      img.alt = 'Imagen agregada';
      img.className = 'img-fluid gallery-thumb-img';
      ratio.appendChild(img);
      card.appendChild(ratio);
      const sortId = parseRemoveTokenPayload(removeToken);
      if (sortId) {
        card.dataset.gallerySortId = sortId;
      }
      if (removeToken) {
        const removeBtn = document.createElement('button');
        removeBtn.type = 'submit';
        removeBtn.name = 'remove_gallery_token';
        removeBtn.value = removeToken;
        removeBtn.className = 'btn btn-outline-danger btn-sm w-100';
        removeBtn.dataset.galleryRemove = 'true';
        removeBtn.textContent = 'Quitar';
        attachRemovalConfirm(removeBtn);
        card.appendChild(removeBtn);
      }
      galleryThumbs.appendChild(card);
      enableGalleryDragSort();
    };

    const handleGalleryUrlUpload = async (input) => {
      if (!input || galleryUploadInFlight) return;
      const urlValue = input.value.trim();
      if (!urlValue) {
        showGalleryStatus('Ingresá una URL antes de presionar Enter.', 'warning');
        return;
      }
      if (!galleryEndpoint || !galleryContext || galleryContext === 'none') {
        showGalleryStatus('Guardá el producto antes de cargar imágenes por URL.', 'warning');
        return;
      }

      const payload = { url: urlValue, context: galleryContext };
      if (galleryContext === 'preview') {
        payload.row_index = Number(galleryContextId);
      } else if (galleryContext === 'product') {
        payload.product_id = galleryContextId;
      }

      input.disabled = true;
      galleryUploadInFlight = true;
      showGalleryStatus('Subiendo imagen desde URL...', 'info');
      try {
        const response = await fetch(galleryEndpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          throw new Error(data.message || 'No se pudo subir la imagen desde la URL.');
        }
        appendGalleryThumb(data.image_url, data.remove_token);
        input.value = '';
        showGalleryStatus(data.message || 'Imagen agregada correctamente.', 'success');
      } catch (err) {
        showGalleryStatus(err.message || 'No se pudo subir la imagen desde la URL.', 'warning');
      } finally {
        input.disabled = false;
        galleryUploadInFlight = false;
      }
    };

    galleryUrlInputs.forEach((input) => {
      input.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Enter') return;
        ev.preventDefault();
        handleGalleryUrlUpload(input);
      });
    });

    enableGalleryDragSort();
  }
});
