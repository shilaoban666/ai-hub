# Claude Runtime image

Build the image used by `CLAUDE_CODE_SANDBOX_TYPE=container`:

```bash
docker build -t aihub/claude-runtime:latest backend/runtime_images/claude
```

AI Hub overrides the image user with the backend service UID so bind-mounted
Run views remain writable. Each Run also enables a read-only root filesystem,
drops all Linux capabilities, enables `no-new-privileges`, limits CPU, memory
and PIDs, and never mounts the Docker socket.

Update `CLAUDE_CODE_VERSION` deliberately and rebuild the image when upgrading
Claude Code. Do not use an unpinned `latest` npm package inside production
builds.
