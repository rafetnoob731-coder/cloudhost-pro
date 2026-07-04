import os
import uuid
import json
import mimetypes
import subprocess
import shutil
import tempfile
import signal
import re
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, send_from_directory, jsonify, abort, session, Response
)

# ─── App Configuration ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', uuid.uuid4().hex)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'.py', '.zip', '.js'}
app.config['MAX_FILE_AGE'] = timedelta(days=30)
app.config['TERMINAL_TIMEOUT'] = 15  # seconds

# ─── Admin Configuration ─────────────────────────────────────────
app.config['ADMIN_USERNAME'] = 'admin'
app.config['ADMIN_PASSWORD'] = 'admin123'

# Ensure upload directory exists
Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)

# ─── Helpers ──────────────────────────────────────────────────────────


def allowed_file(filename):
    """Check if file extension is allowed."""
    return Path(filename).suffix.lower() in app.config['ALLOWED_EXTENSIONS']


def get_file_info(filepath):
    """Return dict with metadata for a given file path (relative to uploads)."""
    full_path = Path(app.config['UPLOAD_FOLDER']) / filepath
    if not full_path.exists() or not full_path.is_file():
        return None
    stat = full_path.stat()
    size = stat.st_size

    if size < 1024:
        size_str = f"{size} B"
    elif size < 1024 ** 2:
        size_str = f"{size / 1024:.1f} KB"
    else:
        size_str = f"{size / 1024 ** 2:.1f} MB"

    suffix = full_path.suffix.lower()
    icon_map = {
        '.py': '🐍',
        '.zip': '📦',
        '.js': '📜',
    }
    color_map = {
        '.py': '#3776AB',
        '.zip': '#F7A41D',
        '.js': '#F7DF1E',
    }
    return {
        'name': full_path.name,
        'path': filepath.replace('\\', '/'),
        'size': size,
        'size_str': size_str,
        'ext': suffix,
        'icon': icon_map.get(suffix, '📄'),
        'color': color_map.get(suffix, '#6c757d'),
        'uploaded': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M'),
        'download_url': url_for('serve_file', filename=filepath.replace('\\', '/'), _external=True),
    }


def get_dir_info(dirpath):
    """Return dict for a directory."""
    full_path = Path(app.config['UPLOAD_FOLDER']) / dirpath
    if not full_path.exists() or not full_path.is_dir():
        return None
    stat = full_path.stat()
    return {
        'name': full_path.name,
        'path': dirpath.replace('\\', '/'),
        'type': 'directory',
        'icon': '📁',
        'color': '#6c5ce7',
        'uploaded': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M'),
    }


def build_file_tree(base_path=None):
    """Build a nested file/folder tree structure."""
    if base_path is None:
        base_path = Path(app.config['UPLOAD_FOLDER'])
    else:
        base_path = Path(app.config['UPLOAD_FOLDER']) / base_path

    if not base_path.exists():
        return []

    items = []
    for entry in sorted(base_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        rel_path = str(entry.relative_to(Path(app.config['UPLOAD_FOLDER'])))
        if entry.is_dir():
            children = build_file_tree(rel_path)
            items.append({
                'name': entry.name,
                'path': rel_path.replace('\\', '/'),
                'type': 'directory',
                'icon': '📁',
                'color': '#6c5ce7',
                'children': children,
                'uploaded': datetime.fromtimestamp(entry.stat().st_ctime).strftime('%Y-%m-%d %H:%M'),
            })
        elif entry.suffix.lower() in app.config['ALLOWED_EXTENSIONS']:
            info = get_file_info(rel_path)
            if info:
                items.append(info)
    return items


def list_files_flat(base_path=None):
    """Return flat list of all files, optionally filtered by subpath."""
    search_path = Path(app.config['UPLOAD_FOLDER'])
    if base_path:
        search_path = search_path / base_path

    if not search_path.exists():
        return []

    files = []
    for f in search_path.rglob('*'):
        if f.is_file() and f.suffix.lower() in app.config['ALLOWED_EXTENSIONS']:
            rel = str(f.relative_to(Path(app.config['UPLOAD_FOLDER'])))
            info = get_file_info(rel)
            if info:
                files.append(info)
    files.sort(key=lambda x: x['uploaded'], reverse=True)
    return files


def clean_old_files():
    """Remove files older than MAX_FILE_AGE."""
    upload_dir = Path(app.config['UPLOAD_FOLDER'])
    now = datetime.now()
    for f in upload_dir.rglob('*'):
        if f.is_file():
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if now - mtime > app.config['MAX_FILE_AGE']:
                try:
                    f.unlink()
                except OSError:
                    pass

    # Remove empty directories
    for d in sorted(upload_dir.rglob('*'), key=lambda x: len(str(x)), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
            except OSError:
                pass


def safe_execute(code, language='python'):
    """Execute Python or JS code safely with timeout. Returns output."""
    if language == 'python':
        cmd = ['python3', '-c', code]
    elif language == 'javascript':
        cmd = ['node', '-e', code]
    else:
        return 'Error: Unsupported language. Use python or javascript.'

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=app.config['TERMINAL_TIMEOUT'],
            cwd=tempfile.mkdtemp(),
        )
        output = result.stdout
        if result.stderr:
            output += '\n' + ('─' * 40) + '\nSTDERR:\n' + result.stderr
        if result.returncode != 0 and not output.strip():
            output = f'Exit code: {result.returncode}\n{result.stderr}'
        return output.strip() or '(no output)'
    except subprocess.TimeoutExpired:
        return f'Error: Execution timed out after {app.config["TERMINAL_TIMEOUT"]} seconds.'
    except FileNotFoundError:
        return f'Error: {language} runtime not found on server.'
    except Exception as e:
        return f'Error: {str(e)}'


# ─── Routes ───────────────────────────────────────────────────────────


@app.route('/')
def index():
    clean_old_files()
    recent = list_files_flat()[:8]
    stats = {
        'total_files': len(list_files_flat()),
        'total_size': sum(f['size'] for f in list_files_flat()),
        'supported_types': ['PY', 'ZIP', 'JS'],
    }
    return render_template('index.html', recent=recent, stats=stats)


@app.route('/browse')
def browse():
    files = list_files_flat()
    return render_template('browse.html', files=files)


@app.route('/files')
def file_manager():
    """File manager page with tree view."""
    return render_template('files.html')


@app.route('/terminal')
def terminal_page():
    """Web terminal page."""
    return render_template('terminal.html')


# ─── Upload ──────────────────────────────────────────────────────

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided.'}), 400

    files = request.files.getlist('file')
    target_dir = request.form.get('path', '').strip('/')
    uploaded = []

    upload_base = Path(app.config['UPLOAD_FOLDER'])
    if target_dir:
        target_path = upload_base / target_dir
        # Security: prevent directory traversal
        try:
            target_path.resolve().relative_to(upload_base.resolve())
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid path.'}), 400
        target_path.mkdir(parents=True, exist_ok=True)
    else:
        target_path = upload_base

    for file in files:
        if file.filename == '':
            continue

        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'message': f'❌ "{file.filename}" — Only .py, .zip, .js files are allowed.'
            }), 400

        original_name = file.filename
        stem = Path(original_name).stem
        suffix = Path(original_name).suffix
        unique_name = f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

        filepath = target_path / unique_name
        file.save(str(filepath))

        rel_path = str(filepath.relative_to(upload_base))
        info = get_file_info(rel_path)
        if info:
            uploaded.append(info)

    if not uploaded:
        return jsonify({'success': False, 'message': 'No valid files uploaded.'}), 400

    return jsonify({
        'success': True,
        'message': f'✅ {len(uploaded)} file(s) uploaded successfully!',
        'files': uploaded,
    })


@app.route('/uploads/<path:filename>')
def serve_file(filename):
    """Serve a file for download / viewing."""
    upload_base = Path(app.config['UPLOAD_FOLDER'])
    filepath = upload_base / filename
    try:
        filepath.resolve().relative_to(upload_base.resolve())
    except ValueError:
        abort(404)

    if not filepath.exists() or not filepath.is_file():
        abort(404)

    suffix = filepath.suffix.lower()
    as_attachment = suffix == '.zip'
    mimetype, _ = mimetypes.guess_type(str(filepath))
    return send_from_directory(
        upload_base,
        filename,
        as_attachment=as_attachment,
        mimetype=mimetype,
    )


@app.route('/preview/<path:filename>')
def preview_file(filename):
    """Return file content as text for preview (only .py and .js)."""
    upload_base = Path(app.config['UPLOAD_FOLDER'])
    filepath = upload_base / filename
    try:
        filepath.resolve().relative_to(upload_base.resolve())
    except ValueError:
        abort(404)

    if not filepath.exists():
        abort(404)
    suffix = filepath.suffix.lower()
    if suffix not in ('.py', '.js'):
        return jsonify({'success': False, 'message': 'Preview not available for this file type.'}), 400
    try:
        content = filepath.read_text(encoding='utf-8', errors='replace')
        return jsonify({'success': True, 'content': content, 'name': filename})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ─── File Operations ─────────────────────────────────────────────

@app.route('/api/file-tree')
def api_file_tree():
    """Get full file tree."""
    return jsonify(build_file_tree())


@app.route('/api/files')
def api_files():
    """JSON endpoint for flat file list."""
    path = request.args.get('path', '')
    return jsonify(list_files_flat(path) if path else list_files_flat())


@app.route('/api/stats')
def api_stats():
    files = list_files_flat()
    total_size = sum(f['size'] for f in files)
    return jsonify({
        'total_files': len(files),
        'total_size': total_size,
        'total_size_str': f"{total_size / (1024**2):.1f} MB" if total_size > 1024**2 else f"{total_size / 1024:.1f} KB",
    })


@app.route('/delete/<path:filename>', methods=['POST'])
def delete_file(filename):
    """Delete a single file."""
    upload_base = Path(app.config['UPLOAD_FOLDER'])
    filepath = upload_base / filename
    try:
        filepath.resolve().relative_to(upload_base.resolve())
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid path.'}), 400

    if not filepath.exists():
        return jsonify({'success': False, 'message': 'File not found.'}), 404
    try:
        if filepath.is_dir():
            shutil.rmtree(str(filepath))
            return jsonify({'success': True, 'message': f'🗑️ Directory "{filename}" deleted.'})
        else:
            filepath.unlink()
            return jsonify({'success': True, 'message': f'🗑️ "{filename}" deleted.'})
    except OSError as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/rename', methods=['POST'])
def rename_item():
    """Rename a file or directory."""
    data = request.get_json()
    old_path = data.get('oldPath', '')
    new_name = data.get('newName', '')

    if not old_path or not new_name:
        return jsonify({'success': False, 'message': 'Missing parameters.'}), 400

    # Validate new name
    if not re.match(r'^[\w\-. ]+$', new_name):
        return jsonify({'success': False, 'message': 'Invalid name. Use letters, numbers, hyphens, underscores, dots.'}), 400

    upload_base = Path(app.config['UPLOAD_FOLDER'])
    src = upload_base / old_path
    dst = src.parent / new_name

    try:
        src.resolve().relative_to(upload_base.resolve())
        dst.resolve().relative_to(upload_base.resolve())
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid path.'}), 400

    if not src.exists():
        return jsonify({'success': False, 'message': 'File/folder not found.'}), 404

    if dst.exists():
        return jsonify({'success': False, 'message': 'A file/folder with that name already exists.'}), 409

    try:
        src.rename(dst)
        return jsonify({'success': True, 'message': f'✅ Renamed to "{new_name}".'})
    except OSError as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/folder/create', methods=['POST'])
def create_folder():
    """Create a new folder."""
    data = request.get_json()
    folder_name = data.get('name', '')
    parent_path = data.get('parent', '')

    if not folder_name:
        return jsonify({'success': False, 'message': 'Folder name required.'}), 400

    if not re.match(r'^[\w\-. ]+$', folder_name):
        return jsonify({'success': False, 'message': 'Invalid name. Use letters, numbers, hyphens, underscores, dots.'}), 400

    upload_base = Path(app.config['UPLOAD_FOLDER'])
    target = upload_base / parent_path / folder_name if parent_path else upload_base / folder_name

    try:
        target.resolve().relative_to(upload_base.resolve())
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid path.'}), 400

    if target.exists():
        return jsonify({'success': False, 'message': 'Folder already exists.'}), 409

    try:
        target.mkdir(parents=True, exist_ok=True)
        return jsonify({'success': True, 'message': f'📁 Folder "{folder_name}" created.'})
    except OSError as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ─── Terminal ────────────────────────────────────────────────────

@app.route('/api/terminal/execute', methods=['POST'])
def terminal_execute():
    """Execute Python/JS code and return output."""
    data = request.get_json()
    code = data.get('code', '')
    language = data.get('language', 'python')

    if not code.strip():
        return jsonify({'output': '', 'language': language})

    # Security: prevent dangerous patterns
    dangerous = ['import os', 'import subprocess', 'import sys', '__import__', 'exec(', 'eval(']
    if language == 'python':
        for pattern in dangerous:
            if pattern in code and 'import socket' not in code:  # Allow basic imports
                return jsonify({
                    'output': f'⛔ Security restriction: "{pattern}" is not allowed in web terminal.',
                    'language': language
                })

    output = safe_execute(code, language)
    return jsonify({'output': output, 'language': language})


@app.route('/api/terminal/run-file', methods=['POST'])
def terminal_run_file():
    """Run an uploaded .py or .js file and return output."""
    data = request.get_json()
    filename = data.get('filename', '')
    language = data.get('language', 'python')

    upload_base = Path(app.config['UPLOAD_FOLDER'])
    filepath = upload_base / filename

    try:
        filepath.resolve().relative_to(upload_base.resolve())
    except ValueError:
        return jsonify({'output': 'Invalid path.'}), 400

    if not filepath.exists():
        return jsonify({'output': 'File not found.'}), 404

    try:
        code = filepath.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        return jsonify({'output': f'Error reading file: {str(e)}'})

    output = safe_execute(code, language)
    return jsonify({'output': output, 'language': language})


# ─── Admin Auth ───────────────────────────────────────────────────────

def admin_required(f):
    """Decorator to require admin login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ─── Admin Routes ─────────────────────────────────────────────────

@app.route('/admin')
def admin_login():
    """Admin entry point — redirects to unified login."""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('user_login_page'))


@app.route('/admin/logout')
def admin_logout():
    """Logout admin — redirects to /login."""
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    session.pop('user_logged_in', None)
    session.pop('user_username', None)
    return redirect(url_for('user_login_page'))


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard with stats."""
    files = list_files_flat()
    total_size = sum(f['size'] for f in files)
    size_str = f"{total_size / (1024**2):.1f} MB" if total_size > 1024**2 else f"{total_size / 1024:.1f} KB"

    # Count by type
    py_count = len([f for f in files if f['ext'] == '.py'])
    js_count = len([f for f in files if f['ext'] == '.js'])
    zip_count = len([f for f in files if f['ext'] == '.zip'])

    # System info
    import sys
    system_info = {
        'python_version': sys.version.split()[0],
        'platform': sys.platform,
        'uptime_days': (datetime.now() - datetime.fromtimestamp(Path(app.instance_path).stat().st_ctime)).days if Path(app.instance_path).exists() else 0,
        'total_uploads': len(files),
        'total_size': size_str,
        'upload_dir': app.config['UPLOAD_FOLDER'],
    }

    return render_template('admin.html',
                         dashboard=True,
                         files=files[:20],  # Latest 20
                         stats={
                             'total_files': len(files),
                             'total_size': size_str,
                             'py_count': py_count,
                             'js_count': js_count,
                             'zip_count': zip_count,
                         },
                         system_info=system_info,
                         default_quota=DEFAULT_QUOTA)


@app.route('/admin/files')
@admin_required
def admin_files():
    """Admin file manager (all files)."""
    files = list_files_flat()
    return render_template('admin.html',
                         file_manager=True,
                         files=files,
                         default_quota=DEFAULT_QUOTA)


@app.route('/admin/api/activity')
@admin_required
def admin_activity():
    """Get recent activity log (file operations)."""
    files = list_files_flat()[:50]
    activity = []
    for f in files:
        activity.append({
            'action': 'upload',
            'file': f['name'],
            'size': f['size_str'],
            'time': f['uploaded'],
            'icon': f['icon'],
        })
    return jsonify(activity)


@app.route('/admin/api/clear-all', methods=['POST'])
@admin_required
def admin_clear_all():
    """Delete all files from uploads."""
    upload_dir = Path(app.config['UPLOAD_FOLDER'])
    count = 0
    for f in upload_dir.rglob('*'):
        if f.is_file() and f.suffix.lower() in app.config['ALLOWED_EXTENSIONS']:
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
    # Remove empty dirs
    for d in sorted(upload_dir.rglob('*'), key=lambda x: len(str(x)), reverse=True):
        if d.is_dir() and not any(d.iterdir()) and d != upload_dir:
            try:
                d.rmdir()
            except OSError:
                pass
    return jsonify({'success': True, 'message': f'🗑️ Deleted {count} files.', 'count': count})


# ─── Admin Professional Pages ────────────────────────────────────

@app.route('/admin/createuser')
@admin_required
def admin_create_user_page():
    """Admin create user page."""
    return render_template('admin.html',
                         create_user_page=True,
                         default_quota=DEFAULT_QUOTA)


@app.route('/admin/userlist')
@admin_required
def admin_userlist():
    """Admin user list page."""
    users = load_users()
    users_list = []
    for uname, data in users.items():
        user_files_count = len(get_user_files(uname))
        storage_used = get_user_storage_used(uname)
        storage_total = data.get('storage_mb', DEFAULT_QUOTA['storage_mb']) * 1024 * 1024
        users_list.append({
            'username': uname,
            'active': data.get('active', True),
            'ram_mb': data.get('ram_mb', DEFAULT_QUOTA['ram_mb']),
            'cpu_cores': data.get('cpu_cores', DEFAULT_QUOTA['cpu_cores']),
            'storage_mb': data.get('storage_mb', DEFAULT_QUOTA['storage_mb']),
            'max_files': data.get('max_files', DEFAULT_QUOTA['max_files']),
            'files_count': user_files_count,
            'storage_used_str': f"{storage_used / (1024**2):.1f} MB" if storage_used > 1024**2 else f"{storage_used / 1024:.1f} KB",
            'storage_total_str': f'{storage_total / (1024**2):.0f} MB',
            'created_at': data.get('created_at', 'Unknown'),
        })
    return render_template('admin.html',
                         userlist_page=True,
                         users=users_list,
                         default_quota=DEFAULT_QUOTA)


@app.route('/admin/manage')
@admin_required
def admin_manage():
    """Admin management page (files, system)."""
    files = list_files_flat()
    total_size = sum(f['size'] for f in files)
    return render_template('admin.html',
                         manage_page=True,
                         files=files,
                         total_size_str=f"{total_size / (1024**2):.1f} MB" if total_size > 1024**2 else f"{total_size / 1024:.1f} KB",
                         default_quota=DEFAULT_QUOTA)


# ─── Site Settings ────────────────────────────────────────────────────

SETTINGS_FILE = os.path.join(app.root_path, 'settings.json')

DEFAULT_SETTINGS = {
    'site_name': 'CloudHost Pro',
    'site_description': 'Fast & secure file hosting for developers.',
    'max_file_size_mb': 100,
    'auto_clean_days': 30,
    'allowed_extensions': '.py,.zip,.js',
    'default_ram_mb': 512,
    'default_cpu_cores': 1,
    'default_storage_mb': 500,
    'default_max_files': 50,
    'maintenance_mode': False,
    'registration_open': False,
    'telegram_link': '#',
    'footer_text': 'Dev by VIP DARK GOD ⚡',
}


def load_settings():
    """Load settings from JSON file."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
                # Merge with defaults so new keys are always present
                merged = DEFAULT_SETTINGS.copy()
                merged.update(saved)
                return merged
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """Save settings to JSON file."""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


def apply_settings():
    """Apply loaded settings to Flask app config."""
    settings = load_settings()
    app.config['MAX_CONTENT_LENGTH'] = settings.get('max_file_size_mb', 100) * 1024 * 1024
    app.config['MAX_FILE_AGE'] = timedelta(days=settings.get('auto_clean_days', 30))
    app.config['ALLOWED_EXTENSIONS'] = set(ext.strip().lower() for ext in settings.get('allowed_extensions', '.py,.zip,.js').split(',') if ext.strip())
    app.config['SITE_NAME'] = settings.get('site_name', 'CloudHost Pro')
    app.config['SITE_DESCRIPTION'] = settings.get('site_description', '')
    app.config['TELEGRAM_LINK'] = settings.get('telegram_link', '#')
    app.config['FOOTER_TEXT'] = settings.get('footer_text', '')
    
    # Update DEFAULT_QUOTA
    DEFAULT_QUOTA['ram_mb'] = settings.get('default_ram_mb', 512)
    DEFAULT_QUOTA['cpu_cores'] = settings.get('default_cpu_cores', 1)
    DEFAULT_QUOTA['storage_mb'] = settings.get('default_storage_mb', 500)
    DEFAULT_QUOTA['max_files'] = settings.get('default_max_files', 50)
    return settings


@app.route('/admin/settings')
@admin_required
def admin_settings():
    """Admin site settings page."""
    settings = load_settings()
    return render_template('admin.html',
                         settings_page=True,
                         settings=settings,
                         default_quota=DEFAULT_QUOTA)


@app.route('/admin/api/settings', methods=['GET', 'POST'])
@admin_required
def admin_api_settings():
    """Get or update site settings."""
    if request.method == 'GET':
        return jsonify(load_settings())
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided.'}), 400
    
    current = load_settings()
    
    # Update only allowed keys
    allowed_keys = set(DEFAULT_SETTINGS.keys())
    for key, value in data.items():
        if key in allowed_keys:
            # Type casting
            if isinstance(DEFAULT_SETTINGS[key], bool):
                current[key] = bool(value)
            elif isinstance(DEFAULT_SETTINGS[key], int):
                current[key] = int(value)
            elif isinstance(DEFAULT_SETTINGS[key], float):
                current[key] = float(value)
            else:
                current[key] = str(value)
    
    save_settings(current)
    apply_settings()
    
    return jsonify({'success': True, 'message': '✅ Settings saved!'})


# ═══════════════════════════════════════════════════════════════════════
# USER MANAGEMENT SYSTEM
# ═══════════════════════════════════════════════════════════════════════

USERS_FILE = os.path.join(app.root_path, 'users.json')

# Default user quotas
DEFAULT_QUOTA = {
    'ram_mb': 512,
    'cpu_cores': 1,
    'storage_mb': 500,
    'max_files': 50,
}


def load_users():
    """Load users from JSON file."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_users(users):
    """Save users to JSON file."""
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def get_user(username):
    """Get user data by username."""
    users = load_users()
    return users.get(username)


def get_user_files(username):
    """Get files belonging to a specific user (files in their user folder)."""
    user_dir = Path(app.config['UPLOAD_FOLDER']) / username
    if not user_dir.exists():
        return []
    files = []
    for f in user_dir.rglob('*'):
        if f.is_file() and f.suffix.lower() in app.config['ALLOWED_EXTENSIONS']:
            rel = str(f.relative_to(Path(app.config['UPLOAD_FOLDER'])))
            info = get_file_info(rel)
            if info:
                files.append(info)
    files.sort(key=lambda x: x['uploaded'], reverse=True)
    return files


def get_user_storage_used(username):
    """Calculate total storage used by a user."""
    files = get_user_files(username)
    return sum(f['size'] for f in files)


def user_required(f):
    """Decorator to require user login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_logged_in'):
            return redirect(url_for('user_login_page'))
        return f(*args, **kwargs)
    return decorated


# ─── User Routes ─────────────────────────────────────────────────

@app.route('/login')
def user_login_page():
    """Unified login page for both users and admin."""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    if session.get('user_logged_in'):
        return redirect(url_for('user_dashboard'))
    return render_template('user_login.html', error=None)


@app.route('/login/auth', methods=['POST'])
def user_login():
    """Authenticate user OR admin. Unified login."""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        return render_template('user_login.html', error='❌ Please enter username and password.')

    # ─── Check admin credentials first ───
    if username == app.config['ADMIN_USERNAME'] and password == app.config['ADMIN_PASSWORD']:
        session['admin_logged_in'] = True
        session['admin_username'] = username
        session['user_logged_in'] = False
        session.pop('user_username', None)
        return redirect(url_for('admin_dashboard'))

    # ─── Check regular user ───
    users = load_users()
    user = users.get(username)

    if not user or user['password'] != password:
        return render_template('user_login.html', error='❌ Invalid username or password.')

    if not user.get('active', True):
        return render_template('user_login.html', error='❌ Account is deactivated. Contact admin.')

    session['user_logged_in'] = True
    session['user_username'] = username
    session['admin_logged_in'] = False
    session.pop('admin_username', None)
    return redirect(url_for('user_dashboard'))


@app.route('/logout')
def user_logout():
    """Logout user or admin. Clears everything."""
    session.pop('user_logged_in', None)
    session.pop('user_username', None)
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return redirect(url_for('user_login_page'))


@app.route('/dashboard')
@user_required
def user_dashboard():
    """User dashboard showing allocated resources."""
    username = session['user_username']
    user = get_user(username)
    if not user:
        return redirect(url_for('user_logout'))

    files = get_user_files(username)
    storage_used = get_user_storage_used(username)
    storage_total = user.get('storage_mb', DEFAULT_QUOTA['storage_mb']) * 1024 * 1024
    storage_pct = min(100, round((storage_used / storage_total) * 100, 1)) if storage_total > 0 else 0

    ram_total = user.get('ram_mb', DEFAULT_QUOTA['ram_mb'])
    cpu_total = user.get('cpu_cores', DEFAULT_QUOTA['cpu_cores'])
    max_files = user.get('max_files', DEFAULT_QUOTA['max_files'])

    return render_template('user_dashboard.html',
                         user=user,
                         username=username,
                         files=files[:12],
                         stats={
                             'total_files': len(files),
                             'storage_used': storage_used,
                             'storage_total': storage_total,
                             'storage_pct': storage_pct,
                             'storage_used_str': f"{storage_used / (1024**2):.1f} MB" if storage_used > 1024**2 else f"{storage_used / 1024:.1f} KB",
                             'storage_total_str': f"{storage_total / (1024**2):.0f} MB",
                             'ram': ram_total,
                             'cpu': cpu_total,
                             'max_files': max_files,
                             'files_left': max_files - len(files),
                         })


@app.route('/user/files')
@user_required
def user_files():
    """User file manager."""
    username = session['user_username']
    user = get_user(username)
    if not user:
        return redirect(url_for('user_logout'))

    files = get_user_files(username)
    return render_template('user_dashboard.html', file_manager=True, user=user, username=username, files=files)


@app.route('/api/user/stats')
@user_required
def user_stats_api():
    """User stats JSON."""
    username = session['user_username']
    user = get_user(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    files = get_user_files(username)
    storage_used = get_user_storage_used(username)
    storage_total = user.get('storage_mb', DEFAULT_QUOTA['storage_mb']) * 1024 * 1024

    return jsonify({
        'username': username,
        'total_files': len(files),
        'storage_used': storage_used,
        'storage_total': storage_total,
        'storage_pct': min(100, round((storage_used / storage_total) * 100, 1)) if storage_total > 0 else 0,
        'ram_mb': user.get('ram_mb', DEFAULT_QUOTA['ram_mb']),
        'cpu_cores': user.get('cpu_cores', DEFAULT_QUOTA['cpu_cores']),
        'max_files': user.get('max_files', DEFAULT_QUOTA['max_files']),
    })


@app.route('/api/user/upload', methods=['POST'])
@user_required
def user_upload():
    """Upload file to user's folder."""
    username = session['user_username']
    user = get_user(username)
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404

    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided.'}), 400

    # Check storage quota
    current_storage = get_user_storage_used(username)
    max_storage = user.get('storage_mb', DEFAULT_QUOTA['storage_mb']) * 1024 * 1024

    files = request.files.getlist('file')
    total_new_size = 0
    for f in files:
        f.seek(0, 2)  # seek to end
        total_new_size += f.tell()
        f.seek(0)  # seek back to start

    if current_storage + total_new_size > max_storage:
        return jsonify({
            'success': False,
            'message': f'❌ Storage limit exceeded! Used: {current_storage / (1024**2):.1f}MB / {max_storage / (1024**2):.0f}MB'
        }), 400

    # Check file count
    existing_files = get_user_files(username)
    max_files = user.get('max_files', DEFAULT_QUOTA['max_files'])
    if len(existing_files) + len(files) > max_files:
        return jsonify({
            'success': False,
            'message': f'❌ File limit exceeded! Max {max_files} files.'
        }), 400

    user_dir = Path(app.config['UPLOAD_FOLDER']) / username
    user_dir.mkdir(parents=True, exist_ok=True)

    uploaded = []
    for file in files:
        if file.filename == '':
            continue

        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'message': f'❌ "{file.filename}" — Only .py, .zip, .js files are allowed.'
            }), 400

        original_name = file.filename
        stem = Path(original_name).stem
        suffix = Path(original_name).suffix
        unique_name = f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

        filepath = user_dir / unique_name
        file.save(str(filepath))

        rel_path = str(filepath.relative_to(Path(app.config['UPLOAD_FOLDER'])))
        info = get_file_info(rel_path)
        if info:
            uploaded.append(info)

    if not uploaded:
        return jsonify({'success': False, 'message': 'No valid files.'}), 400

    return jsonify({
        'success': True,
        'message': f'✅ {len(uploaded)} file(s) uploaded!',
        'files': uploaded,
    })


# ─── Admin User Management Routes ────────────────────────────────

@app.route('/admin/users')
@admin_required
def admin_users():
    """Admin user management page."""
    users = load_users()
    users_list = []
    for uname, data in users.items():
        user_files = get_user_files(uname)
        storage_used = get_user_storage_used(uname)
        storage_total = data.get('storage_mb', DEFAULT_QUOTA['storage_mb']) * 1024 * 1024
        users_list.append({
            'username': uname,
            'password': data.get('password', ''),
            'active': data.get('active', True),
            'ram_mb': data.get('ram_mb', DEFAULT_QUOTA['ram_mb']),
            'cpu_cores': data.get('cpu_cores', DEFAULT_QUOTA['cpu_cores']),
            'storage_mb': data.get('storage_mb', DEFAULT_QUOTA['storage_mb']),
            'max_files': data.get('max_files', DEFAULT_QUOTA['max_files']),
            'files_count': len(user_files),
            'storage_used_str': f"{storage_used / (1024**2):.1f} MB" if storage_used > 1024**2 else f"{storage_used / 1024:.1f} KB",
            'storage_total_str': f'{storage_total / (1024**2):.0f} MB',
            'created_at': data.get('created_at', 'Unknown'),
        })

    return render_template('admin.html',
                         users_management=True,
                         users=users_list,
                         default_quota=DEFAULT_QUOTA)


@app.route('/admin/api/users', methods=['POST'])
@admin_required
def admin_create_user():
    """Create a new user."""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password required.'}), 400

    if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
        return jsonify({'success': False, 'message': 'Username must be 3-20 chars, letters/numbers/underscores.'}), 400

    if len(password) < 4:
        return jsonify({'success': False, 'message': 'Password must be at least 4 characters.'}), 400

    users = load_users()
    if username in users:
        return jsonify({'success': False, 'message': 'Username already exists.'}), 409

    ram = int(data.get('ram_mb', DEFAULT_QUOTA['ram_mb']))
    cpu = int(data.get('cpu_cores', DEFAULT_QUOTA['cpu_cores']))
    storage = int(data.get('storage_mb', DEFAULT_QUOTA['storage_mb']))
    max_files = int(data.get('max_files', DEFAULT_QUOTA['max_files']))

    users[username] = {
        'password': password,
        'active': True,
        'ram_mb': max(128, min(ram, 32000)),
        'cpu_cores': max(0.5, min(cpu, 32)),
        'storage_mb': max(50, min(storage, 100000)),
        'max_files': max(5, min(max_files, 10000)),
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }
    save_users(users)

    # Create user directory
    user_dir = Path(app.config['UPLOAD_FOLDER']) / username
    user_dir.mkdir(parents=True, exist_ok=True)

    return jsonify({'success': True, 'message': f'✅ User "{username}" created!'})


@app.route('/admin/api/users/<username>', methods=['PUT'])
@admin_required
def admin_update_user(username):
    """Update user quota."""
    data = request.get_json()
    users = load_users()

    if username not in users:
        return jsonify({'success': False, 'message': 'User not found.'}), 404

    if 'ram_mb' in data:
        users[username]['ram_mb'] = max(128, min(int(data['ram_mb']), 32000))
    if 'cpu_cores' in data:
        users[username]['cpu_cores'] = max(0.5, min(float(data['cpu_cores']), 32))
    if 'storage_mb' in data:
        users[username]['storage_mb'] = max(50, min(int(data['storage_mb']), 100000))
    if 'max_files' in data:
        users[username]['max_files'] = max(5, min(int(data['max_files']), 10000))
    if 'active' in data:
        users[username]['active'] = bool(data['active'])
    if 'password' in data and data['password'].strip():
        users[username]['password'] = data['password'].strip()

    save_users(users)
    return jsonify({'success': True, 'message': f'✅ User "{username}" updated!'})


@app.route('/admin/api/users/<username>', methods=['DELETE'])
@admin_required
def admin_delete_user(username):
    """Delete a user."""
    users = load_users()
    if username not in users:
        return jsonify({'success': False, 'message': 'User not found.'}), 404

    del users[username]
    save_users(users)

    # Optionally remove user files
    user_dir = Path(app.config['UPLOAD_FOLDER']) / username
    if user_dir.exists():
        shutil.rmtree(str(user_dir))

    return jsonify({'success': True, 'message': f'🗑️ User "{username}" deleted.'})


# ─── Template Context ────────────────────────────────────────────────

@app.context_processor
def inject_user_status():
    """Inject user login status into all templates."""
    return {
        'user_logged_in': session.get('user_logged_in', False),
        'user_username': session.get('user_username', ''),
        'admin_logged_in': session.get('admin_logged_in', False),
    }


# ─── Favicon ──────────────────────────────────────────────────────────

@app.route('/favicon.ico')
def favicon():
    return '', 204


# ─── Error Handlers ───────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'message': '❌ File too large. Max 100 MB.'}), 413


# ─── Entry Point ──────────────────────────────────────────────────────

# ─── Apply settings on startup ──────────────────────────────────
with app.app_context():
    apply_settings()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    print(f"🚀 CloudHost Pro running on http://127.0.0.1:{port}")
    print(f"📁 Uploads: {app.config['UPLOAD_FOLDER']}")
    app.run(host='0.0.0.0', port=port, debug=debug)
