import os
import io
import re
import shutil
import tempfile
import zipfile
import yaml


# 技能文件树用于编辑文本文件。二进制资源不能按 UTF-8 展开后放进 JSON，
# 否则一个字体或 Excel 文件就会把详情接口响应放大几十倍。
BINARY_FILE_EXTENSIONS = {
    '.7z', '.avif', '.bin', '.bmp', '.class', '.doc', '.docx', '.eot', '.gif',
    '.gz', '.ico', '.jpeg', '.jpg', '.otf', '.pdf', '.png', '.ppt', '.pptx',
    '.rar', '.so', '.tar', '.tgz', '.ttf', '.wav', '.webp', '.woff', '.woff2',
    '.xls', '.xlsx', '.zip',
}


def skill_file_content(path: str, raw: bytes, *, include_binary: bool = False) -> dict:
    """Keep resource bytes separate from the editor's JSON text content."""
    content = None
    if os.path.splitext(path)[1].lower() not in BINARY_FILE_EXTENSIONS and b'\x00' not in raw:
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            pass
    result = {'content': content if content is not None else '', 'size': len(raw)}
    if content is None:
        result['is_binary'] = True
    if include_binary:
        result['raw_content'] = raw
    return result


def read_skill_text_file(path: str) -> str:
    """读取可编辑的文本技能文件；二进制资源返回空内容。"""
    extension = os.path.splitext(path)[1].lower()
    if extension in BINARY_FILE_EXTENSIONS:
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()
    except (UnicodeDecodeError, OSError):
        return ''

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
RELEASES_DIR = os.path.join(os.path.dirname(__file__), "releases")
os.makedirs(SKILLS_DIR, exist_ok=True)


class PathTraversalError(ValueError):
    """检测到文件路径穿越攻击（label 含 .. 或绝对路径，企图写出 skill_dir）"""


def resolve_release_file_path(file_path: str | None, file_url: str | None = None) -> str:
    """Resolve a release archive after moving the backend between Windows and WSL."""
    releases_root = os.path.realpath(RELEASES_DIR)
    if file_path:
        candidate = os.path.realpath(file_path)
        try:
            inside = os.path.commonpath([releases_root, candidate]) == releases_root
        except ValueError:
            inside = False
        if inside and os.path.isfile(candidate):
            return candidate

    candidates = []
    for value in (file_url, file_path):
        normalized = str(value or '').replace('\\', '/')
        filename = normalized.rsplit('/', 1)[-1]
        if filename and filename not in candidates:
            candidates.append(filename)

    for filename in candidates:
        if filename in {'.', '..'} or ':' in filename:
            continue
        candidate = os.path.realpath(os.path.join(releases_root, filename))
        try:
            inside = os.path.commonpath([releases_root, candidate]) == releases_root
        except ValueError:
            inside = False
        if not inside:
            continue
        if os.path.isfile(candidate):
            return candidate

    # A missing/unsafe archive must not resolve to an existing external file.
    return ''


def load_release_file_tree(file_path: str, *, include_binary: bool = False) -> list:
    """Load release files without imposing an entrypoint name or location."""
    entries = []
    with zipfile.ZipFile(file_path) as archive:
        for info in archive.infolist():
            raw_path = info.filename.replace('\\', '/')
            normalized_path = raw_path.rstrip('/')
            if not normalized_path:
                continue

            parts = normalized_path.split('/')
            if (
                raw_path.startswith('/')
                or any(part in {'', '.', '..'} for part in parts)
                or parts[0].endswith(':')
            ):
                raise PathTraversalError(f"Invalid release path: {info.filename}")

            content = None
            if not info.is_dir() and not raw_path.endswith('/'):
                content = skill_file_content(raw_path, archive.read(info), include_binary=include_binary)
            entries.append((parts, content))

    if not entries:
        raise ValueError("Release archive is empty")

    # AI Hub release archives wrap the complete skill in one directory.
    first_parts = {parts[0] for parts, _ in entries}
    if len(first_parts) == 1 and any(len(parts) > 1 for parts, _ in entries):
        entries = [(parts[1:], content) for parts, content in entries if len(parts) > 1]

    root = {}
    for parts, content in entries:
        if not parts:
            continue
        current = root
        for index, label in enumerate(parts):
            is_last = index == len(parts) - 1
            is_file = is_last and content is not None
            existing = current.get(label)

            if existing is None:
                existing = {
                    'type': 'file' if is_file else 'folder',
                    'content': content if is_file else None,
                    'children': {} if not is_file else None,
                }
                current[label] = existing
            elif existing['type'] == 'file' or is_file:
                raise ValueError(f"Conflicting release path: {'/'.join(parts)}")

            if not is_last:
                current = existing['children']

    next_id = [1]

    def build_tree(nodes: dict, parent_path: str = '') -> list:
        tree = []
        for label in sorted(nodes):
            source = nodes[label]
            path = f"{parent_path}/{label}" if parent_path else label
            node = {
                'id': next_id[0],
                'label': label,
                'type': source['type'],
                'path': path,
            }
            next_id[0] += 1
            if source['type'] == 'file':
                node.update(source['content'])
            else:
                node['children'] = build_tree(source['children'], path)
            tree.append(node)
        return tree

    return build_tree(root)


def get_skill_dir(skill_id: int) -> str:
    """获取技能的文件目录路径"""
    skill_dir = os.path.join(SKILLS_DIR, str(skill_id))
    os.makedirs(skill_dir, exist_ok=True)
    return skill_dir


def save_skill_files(skill_id: int, file_tree: list):
    """将文件树保存到文件系统"""
    skill_dir = get_skill_dir(skill_id)
    skill_dir_real = os.path.realpath(skill_dir)

    def _resolve_safe(parent_path: str, label: str) -> str:
        """拼接路径并校验必须落在 skill_dir 内，防止 .. / 绝对路径穿越"""
        full_path = os.path.realpath(os.path.join(skill_dir, parent_path, label))
        if full_path != skill_dir_real and not full_path.startswith(skill_dir_real + os.sep):
            raise PathTraversalError(f"非法文件路径: {label}")
        return full_path

    def validate_node(node, parent_path=""):
        if not isinstance(node, dict):
            raise ValueError("文件树节点必须是对象")
        label = node.get('label', '')
        if not label or label in {'.', '..'} or '/' in label or '\\' in label:
            raise PathTraversalError(f"非法文件路径: {label}")
        node_type = node.get('type')
        if node_type not in {'file', 'folder'}:
            raise ValueError(f"不支持的文件树节点类型: {node_type}")
        if node_type == 'file' and not isinstance(node.get('content', ''), str):
            raise ValueError(f"文件内容必须是文本: {label}")
        if node_type == 'folder' and not isinstance(node.get('children', []), list):
            raise ValueError(f"文件夹 children 必须是数组: {label}")
        _resolve_safe(parent_path, label)
        if node_type == 'folder':
            for child in node.get('children') or []:
                child_parent = os.path.join(parent_path, label) if parent_path else label
                validate_node(child, child_parent)

    # Validate the complete tree before replacing any existing files.
    for node in file_tree:
        validate_node(node)

    def save_node(node, parent_path=""):
        label = node.get('label', '')
        if node.get('type') == 'file':
            target = os.path.join(stage_dir, parent_path, label)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if 'raw_content' in node:
                raw = node['raw_content']
                if not isinstance(raw, bytes):
                    raise ValueError(f"文件原始内容无效: {label}")
                with open(target, 'wb') as handle:
                    handle.write(raw)
            elif node.get('is_binary'):
                if node.get('content'):
                    raise ValueError(f"二进制文件不支持文本编辑: {label}")
                source_path = node.get('original_path') or node.get('path')
                if not isinstance(source_path, str):
                    raise ValueError(f"缺少二进制文件来源: {label}")
                parts = source_path.replace('\\', '/').split('/')
                if any(part in {'', '.', '..'} for part in parts) or ':' in parts[0]:
                    raise PathTraversalError(f"非法文件路径: {source_path}")
                source = _resolve_safe('', os.path.join(*parts))
                if not os.path.isfile(source):
                    raise ValueError(f"二进制文件不存在，请重新导入: {label}")
                shutil.copyfile(source, target)
            else:
                with open(target, 'w', encoding='utf-8', newline='') as handle:
                    handle.write(node.get('content', ''))
        elif node.get('type') == 'folder':
            os.makedirs(os.path.join(stage_dir, parent_path, label), exist_ok=True)
            if node.get('children'):
                for child in node['children']:
                    save_node(child, os.path.join(parent_path, label) if parent_path else label)

    # Stage the complete replacement before deleting files referenced by binary nodes.
    with tempfile.TemporaryDirectory(prefix='.skill-save-', dir=SKILLS_DIR) as stage_dir:
        for node in file_tree:
            save_node(node)
        for item in os.listdir(skill_dir):
            item_path = os.path.join(skill_dir, item)
            if os.path.islink(item_path) or os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        for item in os.listdir(stage_dir):
            shutil.move(os.path.join(stage_dir, item), os.path.join(skill_dir, item))


def load_skill_files(skill_id: int, *, include_binary: bool = False) -> list:
    """从文件系统加载文件树"""
    skill_dir = get_skill_dir(skill_id)
    if not os.path.exists(skill_dir):
        return []

    file_id = 1

    def build_tree(path, parent_path=""):
        nonlocal file_id
        tree = []

        try:
            items = sorted(os.listdir(path))
        except Exception:
            return tree

        for item in items:
            full_path = os.path.join(path, item)
            rel_path = os.path.join(parent_path, item) if parent_path else item

            if os.path.isfile(full_path):
                with open(full_path, 'rb') as handle:
                    file_content = skill_file_content(rel_path, handle.read(), include_binary=include_binary)
                if file_content.get('is_binary'):
                    file_content['original_path'] = rel_path.replace('\\', '/')

                tree.append({
                    'id': file_id,
                    'label': item,
                    'type': 'file',
                    'path': rel_path.replace('\\', '/'),
                    **file_content,
                })
                file_id += 1
            elif os.path.isdir(full_path):
                children = build_tree(full_path, rel_path)
                tree.append({
                    'id': file_id,
                    'label': item,
                    'type': 'folder',
                    'path': rel_path.replace('\\', '/'),
                    'children': children
                })
                file_id += 1

        return tree

    return build_tree(skill_dir)


def delete_skill_files(skill_id: int):
    """删除技能的所有文件"""
    skill_dir = get_skill_dir(skill_id)
    if os.path.exists(skill_dir):
        shutil.rmtree(skill_dir)


def build_skill_archive(file_tree: list, root_folder_name: str) -> bytes:
    """Export original resource bytes instead of the editor's empty placeholders."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        def write_nodes(nodes, parent):
            for node in nodes:
                label = node.get('label', '')
                if not label or label in {'.', '..'} or any(c in label for c in '/\\:\x00'):
                    raise PathTraversalError("非法的发布文件名")
                path = f'{parent}/{label}'
                if node['type'] == 'folder':
                    archive.writestr(path + '/', '')
                    write_nodes(node.get('children', []), path)
                else:
                    if node.get('is_binary') and 'raw_content' not in node:
                        raise ValueError(f"缺少二进制文件原始内容: {label}")
                    archive.writestr(path, node.get('raw_content', node.get('content', '')))
        write_nodes(file_tree, root_folder_name)
    return buffer.getvalue()


def find_skill_md_content(flat_files):
    """Return the outermost SKILL.md, without matching names like other-skill.md."""
    candidates = [path for path in flat_files if path.replace('\\', '/').rsplit('/', 1)[-1].lower() == 'skill.md']
    if not candidates:
        return None
    path = min(candidates, key=lambda value: (value.replace('\\', '/').count('/'), value))
    return flat_files[path]


def parse_skill_md(content: str):
    """解析 SKILL.md 文件内容；未声明的版本留空，由调用方决定是否使用默认值。"""
    metadata = {
        'name': '',
        'version': '',
        'author': '',
        'description': '',
        'roles': '通用'
    }

    frontmatter = re.match(r'\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)', content, re.DOTALL)
    if frontmatter:
        try:
            # BaseLoader preserves version strings and does not construct YAML objects.
            values = yaml.load(frontmatter.group(1), Loader=yaml.BaseLoader)
        except yaml.YAMLError:
            values = None
        if isinstance(values, dict):
            aliases = {'name': ('name', '名称'), 'version': ('version', '版本'),
                       'description': ('description', '简介', '描述')}
            for field, keys in aliases.items():
                for key in keys:
                    if isinstance(values.get(key), str):
                        metadata[field] = values[key].strip()
                        break
            return metadata, content
        # Legacy malformed headers use the old line format, never the instruction body.
        source = frontmatter.group(1)
    else:
        source = content

    name_match = re.search(r'^[ \t]*(?:name|名称)[:：][ \t]*([^\r\n]*)', source, re.MULTILINE | re.IGNORECASE)
    if name_match:
        metadata['name'] = name_match.group(1).strip()

    version_match = re.search(r'^[ \t]*(?:version|版本)[:：][ \t]*([^\r\n]*)', source, re.MULTILINE | re.IGNORECASE)
    if version_match:
        metadata['version'] = version_match.group(1).strip()

    desc_match = re.search(r'^[ \t]*(?:description|简介|描述)[:：][ \t]*([^\r\n]*)', source, re.MULTILINE | re.IGNORECASE)
    if desc_match:
        metadata['description'] = desc_match.group(1).strip()

    return metadata, content


def flatten_file_tree(nodes: list, parent_path: str = "") -> dict[str, str]:
    """将 UI 文件树扁平化为 {path: content} 字典"""
    files = {}
    for node in nodes:
        if node.get('type') == 'file':
            path = node.get('path', node.get('label', ''))
            files[path] = node.get('content', '')
        elif node.get('type') == 'folder' and node.get('children'):
            folder_path = node.get('path', node.get('label', ''))
            child_files = flatten_file_tree(node['children'], folder_path)
            files.update(child_files)
    return files


def build_file_tree_from_flat(flat_files: dict[str, str]) -> list:
    """将 {path: content} 字典转换为 UI 文件树格式"""
    file_id = [1]

    def make_node(path_parts, content, full_path):
        if len(path_parts) == 1:
            node = {
                'id': file_id[0],
                'label': path_parts[0],
                'type': 'file',
                'path': full_path,
                'content': content
            }
            file_id[0] += 1
            return node
        else:
            # This shouldn't happen with proper path splitting
            return None

    # Group files by their top-level path component
    root_nodes = []
    groups = {}  # top_name -> {rest_path: content}

    for path, content in flat_files.items():
        parts = path.split('/', 1)
        name = parts[0]
        rest = parts[1] if len(parts) > 1 else ''
        if name not in groups:
            groups[name] = {}
        groups[name][rest] = content

    for name in sorted(groups.keys()):
        sub = groups[name]
        if '' in sub and len(sub) == 1:
            # It's a file at root level
            node = {
                'id': file_id[0],
                'label': name,
                'type': 'file',
                'path': name,
                'content': sub['']
            }
            file_id[0] += 1
            root_nodes.append(node)
        else:
            # It's a folder - recurse
            children_dict = {k: v for k, v in sub.items() if k != ''}
            children = _build_children(children_dict, name, file_id)
            node = {
                'id': file_id[0],
                'label': name,
                'type': 'folder',
                'path': name,
                'children': children
            }
            file_id[0] += 1
            root_nodes.append(node)

    return root_nodes


def _build_children(flat_files: dict[str, str], parent_path: str, file_id: list) -> list:
    """递归构建子节点"""
    nodes = []
    groups = {}

    for path, content in flat_files.items():
        parts = path.split('/', 1)
        name = parts[0]
        rest = parts[1] if len(parts) > 1 else ''
        if name not in groups:
            groups[name] = {}
        groups[name][rest] = content

    for name in sorted(groups.keys()):
        sub = groups[name]
        full_path = f"{parent_path}/{name}"

        if '' in sub and len(sub) == 1:
            node = {
                'id': file_id[0],
                'label': name,
                'type': 'file',
                'path': full_path,
                'content': sub['']
            }
            file_id[0] += 1
            nodes.append(node)
        else:
            children_dict = {k: v for k, v in sub.items() if k != ''}
            children = _build_children(children_dict, full_path, file_id)
            node = {
                'id': file_id[0],
                'label': name,
                'type': 'folder',
                'path': full_path,
                'children': children
            }
            file_id[0] += 1
            nodes.append(node)

    return nodes
