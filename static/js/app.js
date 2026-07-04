/* ═══════════════════════════════════════════════════════════════════════
   CloudHost Pro — Main Application JS
   ═══════════════════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {

    // ─── Navbar Toggle ───────────────────────────────────────────
    const navToggle = document.getElementById('navToggle');
    const navLinks = document.getElementById('navLinks');

    if (navToggle && navLinks) {
        navToggle.addEventListener('click', () => {
            navToggle.classList.toggle('active');
            navLinks.classList.toggle('open');
        });

        // Close nav on link click
        navLinks.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', () => {
                navToggle.classList.remove('active');
                navLinks.classList.remove('open');
            });
        });
    }

    // ─── Navbar Scroll Effect ────────────────────────────────────
    const navbar = document.getElementById('navbar');
    let lastScroll = 0;

    window.addEventListener('scroll', () => {
        const currentScroll = window.scrollY;
        if (currentScroll > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
        lastScroll = currentScroll;
    });

    // ─── Scroll Animation (Intersection Observer) ────────────────
    const animateElements = document.querySelectorAll('.animate-fade-up, .animate-fade-in');

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px',
    });

    animateElements.forEach(el => observer.observe(el));

    // ─── Hero Stats Counter ──────────────────────────────────────
    const statNumbers = document.querySelectorAll('.hero-stat-number[data-count]');

    const counterObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const target = entry.target;
                const maxCount = parseInt(target.dataset.count);
                animateCounter(target, maxCount);
                counterObserver.unobserve(target);
            }
        });
    }, { threshold: 0.5 });

    statNumbers.forEach(el => counterObserver.observe(el));

    function animateCounter(el, max) {
        if (max === 0) {
            el.textContent = '0';
            return;
        }
        let current = 0;
        const increment = Math.max(1, Math.floor(max / 40));
        const step = () => {
            current += increment;
            if (current >= max) {
                el.textContent = max;
                return;
            }
            el.textContent = current;
            requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }

    // ─── File Upload Dropzone (Home Page) ────────────────────────
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    const uploadProgress = document.getElementById('uploadProgress');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const uploadPreview = document.getElementById('uploadPreview');
    const dropzoneContent = document.getElementById('dropzoneContent');

    if (dropzone && fileInput) {
        // Click to upload
        dropzone.addEventListener('click', (e) => {
            if (e.target.closest('.type-badge') || e.target.closest('.upload-preview-item')) return;
            // Don't trigger if clicking on already uploaded preview items
            fileInput.click();
        });

        // Drag events
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('drag-over');
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            if (e.dataTransfer.files.length) {
                handleFiles(e.dataTransfer.files);
            }
        });

        fileInput.addEventListener('change', function () {
            if (this.files.length) {
                handleFiles(this.files);
            }
        });

        async function handleFiles(files) {
            // Validate file types
            for (let f of files) {
                const ext = '.' + f.name.split('.').pop().toLowerCase();
                if (!['.py', '.zip', '.js'].includes(ext)) {
                    showToast(`❌ "${f.name}" — Only .py, .zip, .js files allowed.`, 'error');
                    return;
                }
            }

            // Show progress
            dropzoneContent.style.display = 'none';
            uploadProgress.style.display = 'flex';
            uploadPreview.style.display = 'none';

            const formData = new FormData();
            for (let f of files) {
                formData.append('file', f);
            }

            // Simulate progress
            let progress = 0;
            const progressInterval = setInterval(() => {
                if (progress < 90) {
                    progress += Math.random() * 15;
                    progressFill.style.width = Math.min(progress, 90) + '%';
                    progressText.textContent = `Uploading... ${Math.floor(Math.min(progress, 90))}%`;
                }
            }, 200);

            try {
                const res = await fetch('/upload', { method: 'POST', body: formData });
                const data = await res.json();

                clearInterval(progressInterval);
                progressFill.style.width = '100%';
                progressText.textContent = data.success ? '✅ Complete!' : '❌ Failed';

                setTimeout(() => {
                    uploadProgress.style.display = 'none';
                    dropzoneContent.style.display = 'block';
                    progressFill.style.width = '0%';

                    if (data.success && data.files) {
                        // Show uploaded files
                        uploadPreview.style.display = 'flex';
                        uploadPreview.innerHTML = data.files.map(f => `
                            <div class="upload-preview-item">
                                <span class="file-emoji-preview">${f.icon}</span>
                                <span class="file-name-preview">${f.name}</span>
                                <span class="file-status">✅</span>
                            </div>
                        `).join('');

                        setTimeout(() => {
                            uploadPreview.style.display = 'none';
                            uploadPreview.innerHTML = '';
                        }, 5000);

                        showToast(data.message, 'success');
                    } else {
                        showToast(data.message || 'Upload failed.', 'error');
                    }
                }, 600);

            } catch (e) {
                clearInterval(progressInterval);
                progressFill.style.width = '0%';
                uploadProgress.style.display = 'none';
                dropzoneContent.style.display = 'block';
                showToast('Upload failed. Server error.', 'error');
            }
        }
    }

    // ─── Toast System ────────────────────────────────────────────
    window.showToast = function (message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = message;

        container.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('toast-out');
            setTimeout(() => toast.remove(), 300);
        }, 3500);
    };

    // ─── Copy Link Buttons ───────────────────────────────────────
    document.querySelectorAll('.copy-link').forEach(btn => {
        btn.addEventListener('click', function () {
            const url = this.dataset.url;
            if (navigator.clipboard) {
                navigator.clipboard.writeText(url).then(() => {
                    showToast('🔗 Link copied to clipboard!', 'success');
                }).catch(() => {
                    fallbackCopy(url);
                });
            } else {
                fallbackCopy(url);
            }
        });
    });

    function fallbackCopy(text) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            showToast('🔗 Link copied!', 'success');
        } catch (e) {
            showToast('Failed to copy link.', 'error');
        }
        document.body.removeChild(ta);
    }

    // ─── Preview File ────────────────────────────────────────────
    document.querySelectorAll('.preview-file').forEach(btn => {
        btn.addEventListener('click', async function () {
            const filename = this.dataset.file;
            await previewFile(filename);
        });
    });

    async function previewFile(filename) {
        try {
            const res = await fetch(`/preview/${encodeURIComponent(filename)}`);
            const data = await res.json();
            if (data.success) {
                document.getElementById('previewTitle').textContent = data.name;
                document.getElementById('previewCode').textContent = data.content;
                document.getElementById('previewModal').classList.add('active');
            } else {
                showToast(data.message, 'error');
            }
        } catch (e) {
            showToast('Error previewing file.', 'error');
        }
    }

    // ─── Delete File ─────────────────────────────────────────────
    document.querySelectorAll('.delete-file').forEach(btn => {
        btn.addEventListener('click', async function () {
            const filename = this.dataset.file;
            if (!confirm(`Delete "${filename}"?`)) return;

            try {
                const res = await fetch(`/delete/${encodeURIComponent(filename)}`, { method: 'POST' });
                const data = await res.json();
                showToast(data.message, data.success ? 'success' : 'error');
                if (data.success) {
                    // Remove card from UI
                    const card = this.closest('.file-card');
                    if (card) {
                        card.style.transition = 'all 0.3s ease';
                        card.style.transform = 'scale(0.9)';
                        card.style.opacity = '0';
                        setTimeout(() => card.remove(), 300);
                    }
                    // Reload if on browse page after short delay
                    if (window.location.pathname === '/browse') {
                        setTimeout(() => window.location.reload(), 500);
                    }
                }
            } catch (e) {
                showToast('Error deleting file.', 'error');
            }
        });
    });

    // ─── Modal Close ─────────────────────────────────────────────
    const previewModal = document.getElementById('previewModal');
    if (previewModal) {
        const closeBtn = document.getElementById('previewClose');
        const backdrop = previewModal.querySelector('.modal-backdrop');

        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                previewModal.classList.remove('active');
            });
        }

        if (backdrop) {
            backdrop.addEventListener('click', () => {
                previewModal.classList.remove('active');
            });
        }

        // Close on Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && previewModal.classList.contains('active')) {
                previewModal.classList.remove('active');
            }
        });
    }

    // ─── Filter Buttons (Browse) ─────────────────────────────────
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');

            const filter = this.dataset.filter;
            const grid = document.getElementById('filesGrid') || document.getElementById('recentGrid');
            if (!grid) return;

            grid.querySelectorAll('.file-card').forEach(card => {
                if (filter === 'all') {
                    card.style.display = 'flex';
                } else {
                    const ext = card.dataset.ext || '';
                    card.style.display = ext === filter ? 'flex' : 'none';
                }
            });
        });
    });

    // ─── Search (Browse) ─────────────────────────────────────────
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function () {
            const query = this.value.toLowerCase();
            const grid = document.getElementById('filesGrid');
            if (!grid) return;

            grid.querySelectorAll('.file-card').forEach(card => {
                const name = card.querySelector('.file-name')?.textContent?.toLowerCase() || '';
                card.style.display = name.includes(query) ? 'flex' : 'none';
            });
        });
    }

    // ─── Smooth scroll for anchor links ──────────────────────────
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            const href = this.getAttribute('href');
            if (href === '#') return;
            const target = document.querySelector(href);
            if (target) {
                e.preventDefault();
                const offset = 80;
                const top = target.getBoundingClientRect().top + window.pageYOffset - offset;
                window.scrollTo({ top, behavior: 'smooth' });
            }
        });
    });

});
