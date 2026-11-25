"""Load image inputs through the workspace provider, including isolated sandboxes."""

import os

from runtimes.base import RuntimeAttachment
from chat_image_storage import read_chat_image, image_object_key


IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024


def build_runtime_attachments(provider, workspace, paths, runtime_type):
    attachments = []
    total_bytes = 0
    for path in dict.fromkeys(paths or []):
        is_oss = path.startswith("https://")
        if is_oss:
            image_object_key(path, workspace.id)
        media_type = IMAGE_TYPES.get(os.path.splitext(path)[1].lower(), "")
        image_data = None
        filename = os.path.basename(path)
        if runtime_type == "claude_code" and media_type:
            # Provider access preserves native sandbox permissions and path checks.
            if is_oss:
                image_data, filename = read_chat_image(path, workspace.id)
            else:
                image_data, filename = provider.read_file_limited(workspace, path, MAX_IMAGE_BYTES)
            if not image_data or len(image_data) > MAX_IMAGE_BYTES:
                raise ValueError(f"Image must be between 1 byte and 5 MB: {filename}")
            total_bytes += len(image_data)
            if total_bytes > MAX_TOTAL_IMAGE_BYTES:
                raise ValueError("Attached images exceed the 20 MB total limit")
        attachments.append(RuntimeAttachment(
            path=path, filename=filename, media_type=media_type, image_data=image_data,
        ))
    return tuple(attachments)
