#!/usr/bin/env bash
# =============================================================================
# 全栈 Docker 编排管理 (xiaozhi-server + manager-api + manager-web + MySQL + Redis)
#
# 用法:
#   ./docker-stack.sh up          # 拉镜像并启动全部容器
#   ./docker-stack.sh down        # 停止并移除容器
#   ./docker-stack.sh status      # 容器状态
#   ./docker-stack.sh logs [svc]  # 查看日志 (svc: server/web/db/redis)
#   ./docker-stack.sh restart     # 重启 xiaozhi-server (改配置后)
#   ./docker-stack.sh bootstrap   # 自动注册管理员并回填 server.secret
#
# 说明:
#   - 复用仓库自带 docker-compose_all.yml, 通过 --project-directory 将
#     相对路径 (data/models/mysql/uploadfile) 解析到本目录, 不改动仓库文件。
#   - 服务器地址/密钥回填到 deploy/data/.config.yaml
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
COMPOSE="$ROOT/main/xiaozhi-server/docker-compose_all.yml"
PROJECT_DIR="$ROOT/my_explorations/digital-human/deploy"
PROJECT_NAME="xiaozhi"
# 开发调试覆盖: 将本地 main/xiaozhi-server/core bind-mount 进容器(见该文件头注释)
SOURCE_OVERRIDE="$ROOT/my_explorations/digital-human/iac/compose.server-source.yml"

# 供 compose 插值 ${XIAOZHI_REPO_ROOT}(覆盖文件中的相对路径基准)
export XIAOZHI_REPO_ROOT="$ROOT"

COMPOSE_ARGS=(--project-name "$PROJECT_NAME" --project-directory "$PROJECT_DIR" -f "$COMPOSE" -f "$SOURCE_OVERRIDE")

case "${1:-up}" in
  up)
    # 镜像源可能被墙/断流;已有本地镜像时不要让 pull 失败阻断启动
    if ! docker compose "${COMPOSE_ARGS[@]}" pull; then
      echo "WARNING: 镜像拉取失败,改用本地已有镜像启动" >&2
    fi
    docker compose "${COMPOSE_ARGS[@]}" up -d --pull never
    echo "---"
    docker compose --project-name "$PROJECT_NAME" ps
    echo "提示: 智控台 http://127.0.0.1:8002  WS:8000  OTA/视觉:8003"
    echo "首次部署请执行: $0 bootstrap"
    ;;
  down)
    docker compose --project-name "$PROJECT_NAME" down
    ;;
  status)
    docker compose --project-name "$PROJECT_NAME" ps
    ;;
  logs)
    docker compose --project-name "$PROJECT_NAME" logs -f --tail=50 "${2:-}"
    ;;
  restart)
    echo "重启 xiaozhi-server (使 data/.config.yaml 生效)..."
    docker restart xiaozhi-esp32-server
    sleep 3
    docker logs --tail=20 xiaozhi-esp32-server
    ;;
  bootstrap)
    VENV_PY="$ROOT/main/digital-human/.venv/bin/python"
    [ -x "$VENV_PY" ] || { echo "venv 不存在, 先运行 setup.sh" >&2; exit 1; }
    # 若 data/.config.yaml 不存在 (全新克隆), 从模板生成 (secret 仍是 PLACEHOLDER, 稍后回填)
    DATA_CFG="$PROJECT_DIR/data/.config.yaml"
    if [ ! -f "$DATA_CFG" ]; then
      mkdir -p "$PROJECT_DIR/data"
      cp "$PROJECT_DIR/config.template.yaml" "$DATA_CFG"
      echo "已从模板生成 $DATA_CFG"
    fi
    "$VENV_PY" -c "import gmssl" 2>/dev/null || "$VENV_PY" -m pip install -q gmssl
    "$VENV_PY" "$ROOT/my_explorations/digital-human/iac/bootstrap-admin.py" \
      --api "http://127.0.0.1:8002/xiaozhi" \
      --redis-container xiaozhi-esp32-server-redis
    ;;
  *)
    echo "unknown arg: $1" >&2; exit 2
    ;;
esac
