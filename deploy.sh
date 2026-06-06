#!/bin/bash

# ===================================================================================
#
#           Nginx Reverse Proxy Deployment Script (China Optimized & Robust)
#
# ===================================================================================
# NOTE: Legacy helper for host-mode proxy. It defaults to integrating with an
# existing nginx installation by dropping an extra server file under conf.d.

# --- 脚本严格模式 ---
set -e
set -o pipefail

# --- 颜色定义 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- 权限变量 ---
SUDO=''

# --- 权限检查 ---
if [ "$(id -u)" -ne 0 ]; then
    if ! command -v sudo >/dev/null; then
        echo -e "${RED}错误: 此脚本需要以 root 权限运行，或者必须安装 'sudo'。${NC}" >&2
        exit 1
    fi
    SUDO='sudo'
    echo -e "${YELLOW}信息: 检测到非 root 用户，将使用 'sudo' 获取权限。${NC}"
fi

# ===================================================================================
#                                 基础检测与环境设置
# ===================================================================================

# --- 检测是否在中国大陆 ---
is_in_china() {
    if [ -z "$_loc" ]; then
        if _loc=$(curl -m 3 -sL https://www.cloudflare.com/cdn-cgi/trace | grep '^loc=' | cut -d= -f2); then
            true
        elif _loc=$(curl -m 3 -sL http://www.qualcomm.cn/cdn-cgi/trace | grep '^loc=' | cut -d= -f2); then
            true
        else
            return 1
        fi
    fi
    [ "$_loc" = CN ]
}

# --- 设置全局变量 (将在解析参数后调用) ---
setup_env() {
    if [[ -n "${CONF_HOME:-}" && -n "${ACME_INSTALL_URL:-}" && -n "${BACKUP_DIR:-}" ]]; then
        return 0
    fi

    # [技巧] 使用字符串拼接定义基础 URL，防止被镜像站的自动替换机制修改 (Anti-Rewrite)
    local GH_RAW_HOST="raw.githubusercontent.com"
    local URL_PREFIX="https://${GH_RAW_HOST}"

    local RAW_URL_BASE="${URL_PREFIX}/buglyz/emby-nginx-manager/main"
    local ACME_OFFICIAL_RAW="${URL_PREFIX}/acmesh-official/acme.sh/master/acme.sh"

    # 确定代理地址: 命令行参数 > 环境变量 > 自动检测
    local effective_gh_proxy="${manual_gh_proxy:-${GH_PROXY}}"
    if [[ -z "$effective_gh_proxy" ]] && is_in_china; then
        # 国内自动使用 gh.llkk.cc 代理
        effective_gh_proxy="https://gh.llkk.cc"
    fi

    # 确保代理地址以 / 结尾 (如果非空)
    if [[ -n "$effective_gh_proxy" && "$effective_gh_proxy" != */ ]]; then
        effective_gh_proxy="${effective_gh_proxy}/"
    fi

    if [[ -n "$effective_gh_proxy" ]]; then
        log_info "使用 GitHub 代理: ${effective_gh_proxy}"

        # 通过代理获取配置 URL
        CONF_HOME="${effective_gh_proxy}${RAW_URL_BASE}"
        ACME_INSTALL_URL="${effective_gh_proxy}${ACME_OFFICIAL_RAW}"
    else
        log_info "未使用 GitHub 代理，使用默认源..."
        CONF_HOME="${RAW_URL_BASE}"
        ACME_INSTALL_URL="${ACME_OFFICIAL_RAW}"
    fi

    readonly CONF_HOME
    readonly BACKUP_DIR="/etc/nginx/backup"
    readonly ACME_INSTALL_URL
}

# ===================================================================================
#                                 辅助函数
# ===================================================================================

# --- 日志函数 ---
log_info() { echo -e "${BLUE}[INFO]${NC} $1" >&2; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1" >&2; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1" >&2; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# --- 错误处理 ---
handle_error() {
    local exit_code=$?
    local line_number=$1
    echo >&2
    echo -e "${RED}--------------------------------------------------------${NC}" >&2
    echo -e "${RED}错误: 脚本在第 $line_number 行意外中止。${NC}" >&2
    echo -e "${RED}退出码: $exit_code${NC}" >&2
    echo -e "${RED}--------------------------------------------------------${NC}" >&2
    exit "$exit_code"
}
trap 'handle_error $LINENO' ERR

# --- 备份函数 ---
backup_file() {
    local file_path="$1"
    local backup_dir="${BACKUP_DIR:-/etc/nginx/backup}"
    last_backup_path=""
    if [ -f "$file_path" ]; then
        $SUDO mkdir -p "$backup_dir"
        local file_name
        file_name=$(basename "$file_path")
        local backup_name="${file_name}.$(date +%Y%m%d%H%M%S).bak"
        $SUDO cp "$file_path" "$backup_dir/$backup_name"
        last_backup_path="$backup_dir/$backup_name"
        log_info "已备份文件 $file_path 至 $backup_dir/$backup_name"
    fi
}

rollback_generated_config() {
    if [[ -z "${generated_conf_path:-}" ]]; then
        return 0
    fi

    if [[ -n "${last_backup_path:-}" && -f "$last_backup_path" ]]; then
        log_warn "正在恢复配置备份: $last_backup_path"
        $SUDO cp "$last_backup_path" "$generated_conf_path"
    elif $SUDO [ -f "$generated_conf_path" ]; then
        log_warn "正在移除未完成部署生成的配置: $generated_conf_path"
        $SUDO rm -f "$generated_conf_path"
    fi
}

# --- 帮助信息 ---
show_help() {
    cat << EOF
用法: $(basename "$0") [选项]

Note: legacy helper for host-mode proxy. By default it integrates with an existing nginx
installation and only writes an extra file under /etc/nginx/conf.d/.

一个强大且安全的 Nginx 反向代理部署脚本 (支持 sudo 和 IPv6)。

部署选项:
  -y, --you-domain <URL>         你的访问域名或完整 URL (支持 IPv6, 如: https://[2400::1]:443)
  -r, --r-domain <URL>           被代理的后端地址 (例如: http://127.0.0.1:8096)
  -m, --cert-domain <域名>       (可选) 手动指定 SSL 证书的主域名。
  -d, --parse-cert-domain        (可选) 自动提取根域名作为证书域名。
  -D, --dns <provider>           (可选) 使用 DNS API 模式申请证书 (例如: cf)。
  -R, --resolver <DNS>           (可选) 手动指定 DNS 解析服务器。
  -c, --template-domain-config <URL>
                                 (可选) 指定自定义 Nginx 配置文件模板。
  --no-proxy-redirect            (可选) 禁用 302/307 重定向代理，后端重定向将直接返回给客户端。
  --gh-proxy <URL>               (可选) 指定 GitHub 加速代理。
  --dry-run                      只预览将写入的配置，不写文件、不申请证书、不重载。

管理选项:
  --menu                         启动交互式管理菜单。
  --list                         只列出本脚本添加的 Emby Nginx 配置。
  --remove <URL>                 移除指定域名的 Nginx 配置和证书。
  -Y, --yes                      非交互模式下自动确认移除。

其他:
  -h, --help                     显示此帮助信息。
EOF
    exit 0
}

# --- DNS 和 IPv6 检测 ---
has_ipv6() {
    ip -6 addr show scope global | grep -q inet6
}

get_resolver_host() {
    local system_dns
    system_dns=$(awk '/^nameserver/ && !seen[$2]++ { print ($2 ~ /:/ ? "["$2"]" : $2) }' /etc/resolv.conf 2>/dev/null | xargs)

    if [[ -n "$system_dns" ]]; then
        echo "$system_dns"
    else
        if is_in_china; then
            echo "223.5.5.5 119.29.29.29"
        else
            echo "1.1.1.1 8.8.8.8"
        fi
    fi
}

# --- URL 解析 (支持 IPv6) ---
parse_url() {
    local url="$1"
    local proto domain port path

    # 提取协议
    if [[ "$url" =~ ^(https?):// ]]; then
        proto="${BASH_REMATCH[1]}"
        url="${url#*://}"
    else
        echo "$url|||" # 无协议则认为无效或纯域名(暂不支持无协议输入)
        return
    fi

    # 提取域名/IP (支持 [IPv6])
    if [[ "$url" =~ ^\[([a-fA-F0-9:.]+)\] ]]; then
        # IPv6 格式 [xxxx:xxxx]
        domain="[${BASH_REMATCH[1]}]"
        url="${url#*]}" # 移除匹配到的 [ipv6]
    else
        # IPv4 或 域名 (提取直到 : / ? #)
        if [[ "$url" =~ ^([^/:?#]+) ]]; then
            domain="${BASH_REMATCH[1]}"
            url="${url#${domain}}"
        fi
    fi

    # 提取端口
    if [[ "$url" =~ ^:([0-9]+) ]]; then
        port="${BASH_REMATCH[1]}"
        url="${url#:${port}}"
    fi

    # 剩余部分为路径
    path="$url"

    echo "$proto|$domain|$port|$path"
}

normalize_url_path() {
    local raw_path="$1"

    raw_path="${raw_path%%#*}"
    raw_path="${raw_path%%\?*}"
    [[ -z "$raw_path" ]] && raw_path="/"
    [[ "$raw_path" != /* ]] && raw_path="/$raw_path"

    while [[ "$raw_path" != "/" && "$raw_path" == */ ]]; do
        raw_path="${raw_path%/}"
    done

    case "$raw_path" in
        *[[:space:]]*|*";"*|*"{"*|*"}"*|*"\""*|*"'"*|*"\\"*)
            return 1
            ;;
    esac

    printf '%s\n' "$raw_path"
}

escape_nginx_regex_literal() {
    printf '%s' "$1" | sed 's/[][\\.^$*+?{}()|]/\\&/g'
}

escape_nginx_rewrite_replacement() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\$/\\\$}"
    printf '%s\n' "$value"
}

# --- 下载文件 (带验证和重试) ---
download_with_verify() {
    local url="$1"
    local output="$2"
    local verify_keyword="$3"

    if curl -fsL "$url" -o "$output"; then
        if [[ -z "$verify_keyword" ]] || grep -q "$verify_keyword" "$output"; then
            return 0
        else
            log_error "下载的文件内容异常: $output"
            return 1
        fi
    else
        log_error "无法下载: $url"
        return 1
    fi
}

# --- acme.sh: 判断证书是否可用 ---
acme_cert_is_issued() {
    local cert_domain="$1"
    "$ACME_SH" --info -d "$cert_domain" --ecc 2>/dev/null | grep -q "RealFullChainPath"
}

# --- acme.sh: 清理失败后残留记录，避免二次申请报错 ---
cleanup_stale_acme_record() {
    local cert_domain="$1"
    if [[ -z "$cert_domain" || ! -f "$ACME_SH" ]]; then
        return 0
    fi

    log_warn "尝试清理 acme.sh 可能残留的证书状态..."
    "$ACME_SH" --remove -d "$cert_domain" --ecc >/dev/null 2>&1 || true
    "$ACME_SH" --remove -d "$cert_domain" >/dev/null 2>&1 || true
}

# --- 获取协议 ---
get_protocol() {
    [[ "$1" == "yes" ]] && echo "http" || echo "https"
}

# --- 是否为 IP 地址 (支持 IPv4 和 IPv6) ---
is_ip_address() {
    local addr="$1"
    # 移除可能存在的方括号
    local clean_addr="${addr#[}"
    clean_addr="${clean_addr%]}"

    # IPv4 检查
    if [[ "$clean_addr" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
        return 0
    fi

    # IPv6 检查 (简单启发式: 包含冒号)
    if [[ "$clean_addr" =~ : ]]; then
        return 0
    fi

    return 1
}

process_url_input() {
    local full_url="$1"
    local domain_type="$2" # "you" or "r"

    if [[ -z "$full_url" ]]; then return; fi

    local temp_domain temp_path temp_port temp_proto normalized_path
    IFS='|' read -r temp_proto temp_domain temp_port temp_path < <(parse_url "$full_url")

    temp_proto=${temp_proto:-https}
    if ! normalized_path=$(normalize_url_path "$temp_path"); then
        log_error "URL path 包含 Nginx 配置不支持的字符: $temp_path"
        exit 1
    fi
    temp_path="$normalized_path"

    local default_port=$([[ "$temp_proto" == "http" ]] && echo 80 || echo 443)
    local is_http=$([[ "$temp_proto" == "http" ]] && echo "yes" || echo "no")

    if [[ "$domain_type" == "you" ]]; then
        you_domain="$temp_domain"
        you_domain_path="$temp_path"
        no_tls="$is_http"
        you_frontend_port="${temp_port:-$default_port}"
    elif [[ "$domain_type" == "r" ]]; then
        r_domain="$temp_domain"
        r_domain_path="$temp_path"
        r_http_frontend="$is_http"
        r_frontend_port="${temp_port:-$default_port}"
    fi
}

get_nginx_conf_dir() {
    echo "${NGINX_CONF_DIR:-/etc/nginx/conf.d}"
}

shorten_text() {
    local text="$1"
    local max_len="$2"
    if ((${#text} > max_len)); then
        printf '%s...' "${text:0:max_len-3}"
    else
        printf '%s' "$text"
    fi
}

conf_metadata_value() {
    local file="$1"
    local key="$2"
    $SUDO awk -v key="$key" '
        BEGIN { pattern = "^[[:space:]]*#[[:space:]]*" key "=" }
        $0 ~ pattern {
            sub(pattern, "")
            sub(/[[:space:]]+#.*$/, "")
            gsub(/^[[:space:]]+|[[:space:]]+$/, "")
            print
            exit
        }
    ' "$file" 2>/dev/null
}

conf_is_managed_emby_config() {
    local file="$1"
    local marker managed_by
    marker=$(conf_metadata_value "$file" "nre_emby_managed")
    managed_by=$(conf_metadata_value "$file" "managed_by")

    [[ "$marker" == "true" || "$managed_by" == "nginx-reverse-emby-deploy" ]]
}

conf_server_name() {
    local file="$1"
    local meta
    meta=$(conf_metadata_value "$file" "domain")
    if [[ -n "$meta" ]]; then
        echo "$meta"
        return 0
    fi

    $SUDO awk '
        /^[[:space:]]*server_name[[:space:]]+/ {
            for (i = 2; i <= NF; i++) {
                value = $i
                gsub(/;/, "", value)
                if (value != "" && value != "_" && value !~ /^\$/) {
                    print value
                    exit
                }
            }
        }
    ' "$file" 2>/dev/null
}

conf_listen_port() {
    local file="$1"
    local meta
    meta=$(conf_metadata_value "$file" "listen_port")
    if [[ -n "$meta" ]]; then
        echo "$meta"
        return 0
    fi

    $SUDO awk '
        function port_from_part(part) {
            gsub(/;/, "", part)
            if (part ~ /^[0-9]+$/) {
                return part
            }
            if (part ~ /:[0-9]+$/) {
                sub(/^.*:/, "", part)
                return part
            }
            return ""
        }
        /^[[:space:]]*listen[[:space:]]+/ {
            for (i = 2; i <= NF; i++) {
                port = port_from_part($i)
                if (port != "") {
                    break
                }
            }
            if (port != "") {
                if ($0 ~ /ssl/ && ssl_port == "") {
                    ssl_port = port
                }
                if (first_port == "") {
                    first_port = port
                }
            }
        }
        END {
            if (ssl_port != "") {
                print ssl_port
            } else if (first_port != "") {
                print first_port
            }
        }
    ' "$file" 2>/dev/null
}

conf_uses_tls() {
    local file="$1"
    if $SUDO grep -Eq '^[[:space:]]*listen[[:space:]].*ssl|^[[:space:]]*ssl_certificate[[:space:]]+' "$file" 2>/dev/null; then
        echo "yes"
    else
        echo "no"
    fi
}

conf_proxy_target() {
    local file="$1"
    local meta website
    meta=$(conf_metadata_value "$file" "backend")
    if [[ -n "$meta" ]]; then
        echo "$meta"
        return 0
    fi

    website=$($SUDO awk '
        /^[[:space:]]*set[[:space:]]+\$website[[:space:]]+/ {
            sub(/^[[:space:]]*set[[:space:]]+\$website[[:space:]]+/, "")
            sub(/;.*/, "")
            gsub(/^[[:space:]]+|[[:space:]]+$/, "")
            print
            exit
        }
    ' "$file" 2>/dev/null)
    if [[ -n "$website" ]]; then
        echo "$website"
        return 0
    fi

    $SUDO awk '
        /^[[:space:]]*proxy_pass[[:space:]]+/ {
            value = $0
            sub(/^[[:space:]]*proxy_pass[[:space:]]+/, "", value)
            sub(/;.*/, "", value)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            print value
            exit
        }
    ' "$file" 2>/dev/null
}

conf_ssl_cert_path() {
    local file="$1"
    $SUDO awk '
        /^[[:space:]]*ssl_certificate[[:space:]]+/ && $1 != "ssl_certificate_key" {
            value = $2
            sub(/;.*/, "", value)
            print value
            exit
        }
    ' "$file" 2>/dev/null
}

conf_ssl_key_path() {
    local file="$1"
    $SUDO awk '
        /^[[:space:]]*ssl_certificate_key[[:space:]]+/ {
            value = $2
            sub(/;.*/, "", value)
            print value
            exit
        }
    ' "$file" 2>/dev/null
}

load_nginx_config_files() {
    local conf_dir
    conf_dir=$(get_nginx_conf_dir)
    CONFIG_FILES=()

    if ! $SUDO [ -d "$conf_dir" ]; then
        log_error "未找到 Nginx 配置目录: $conf_dir"
        return 1
    fi

    while IFS= read -r file; do
        if conf_is_managed_emby_config "$file" && $SUDO grep -Eq '^[[:space:]]*server[[:space:]]*\{' "$file" 2>/dev/null; then
            CONFIG_FILES+=("$file")
        fi
    done < <($SUDO find "$conf_dir" -maxdepth 1 -type f -name '*.conf' 2>/dev/null | sort)

    if ((${#CONFIG_FILES[@]} == 0)); then
        log_warn "当前没有找到由本脚本添加的 Emby Nginx 配置。"
        return 1
    fi
}

find_nginx_conf_file() {
    local domain="$1"
    local port="$2"
    local clean_domain conf_dir candidate file file_domain file_port
    clean_domain="${domain//[\[\]]/}"
    conf_dir=$(get_nginx_conf_dir)

    for candidate in \
        "$conf_dir/${clean_domain}-${port}.conf" \
        "$conf_dir/${clean_domain}.${port}.conf" \
        "$conf_dir/${clean_domain}.conf"; do
        if $SUDO [ -f "$candidate" ] && conf_is_managed_emby_config "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done

    while IFS= read -r file; do
        file_domain=$(conf_server_name "$file")
        file_port=$(conf_listen_port "$file")
        if [[ "$file_domain" == "$domain" && "$file_port" == "$port" ]] && conf_is_managed_emby_config "$file"; then
            echo "$file"
            return 0
        fi
    done < <($SUDO find "$conf_dir" -maxdepth 1 -type f -name '*.conf' 2>/dev/null | sort)

    return 1
}

find_any_nginx_conf_file() {
    local domain="$1"
    local port="$2"
    local clean_domain conf_dir candidate file file_domain file_port
    clean_domain="${domain//[\[\]]/}"
    conf_dir=$(get_nginx_conf_dir)

    for candidate in \
        "$conf_dir/${clean_domain}-${port}.conf" \
        "$conf_dir/${clean_domain}.${port}.conf" \
        "$conf_dir/${clean_domain}.conf"; do
        if $SUDO [ -f "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done

    while IFS= read -r file; do
        file_domain=$(conf_server_name "$file")
        file_port=$(conf_listen_port "$file")
        if [[ "$file_domain" == "$domain" && "$file_port" == "$port" ]]; then
            echo "$file"
            return 0
        fi
    done < <($SUDO find "$conf_dir" -maxdepth 1 -type f -name '*.conf' 2>/dev/null | sort)

    return 1
}

default_nginx_conf_path() {
    local domain="$1"
    local port="$2"
    local clean_domain conf_dir
    clean_domain="${domain//[\[\]]/}"
    conf_dir=$(get_nginx_conf_dir)
    echo "$conf_dir/${clean_domain}-${port}.conf"
}

print_nginx_config_table() {
    local i file domain port tls backend base short_backend

    printf '%-4s %-32s %-7s %-5s %-38s %s\n' "编号" "域名" "端口" "TLS" "后端" "文件"
    printf '%-4s %-32s %-7s %-5s %-38s %s\n' "----" "--------------------------------" "-------" "-----" "--------------------------------------" "----------------"
    for i in "${!CONFIG_FILES[@]}"; do
        file="${CONFIG_FILES[$i]}"
        domain=$(conf_server_name "$file")
        port=$(conf_listen_port "$file")
        tls=$(conf_uses_tls "$file")
        backend=$(conf_proxy_target "$file")
        base=$(basename "$file")
        short_backend=$(shorten_text "${backend:--}" 38)
        printf '%-4s %-32s %-7s %-5s %-38s %s\n' "$((i + 1))" "${domain:--}" "${port:--}" "$tls" "$short_backend" "$base"
    done
}

list_nginx_configs() {
    load_nginx_config_files || return 1
    print_nginx_config_table
}

select_nginx_config() {
    local choice
    load_nginx_config_files || return 1
    print_nginx_config_table
    echo
    read -rp "请选择配置编号: " choice
    if [[ ! "$choice" =~ ^[0-9]+$ ]] || ((choice < 1 || choice > ${#CONFIG_FILES[@]})); then
        log_error "无效的配置编号。"
        return 1
    fi
    selected_conf_file="${CONFIG_FILES[$((choice - 1))]}"
}

show_nginx_config_detail() {
    local file="$1"
    local domain port tls backend cert key
    domain=$(conf_server_name "$file")
    port=$(conf_listen_port "$file")
    tls=$(conf_uses_tls "$file")
    backend=$(conf_proxy_target "$file")
    cert=$(conf_ssl_cert_path "$file")
    key=$(conf_ssl_key_path "$file")

    echo "--------------------------------------------------------"
    echo "配置文件: $file"
    echo "域名: ${domain:--}"
    echo "端口: ${port:--}"
    echo "TLS: $tls"
    echo "后端: ${backend:--}"
    [[ -n "$cert" ]] && echo "证书: $cert"
    [[ -n "$key" ]] && echo "私钥: $key"
    echo "--------------------------------------------------------"
}

view_nginx_configs_menu() {
    local choice
    select_nginx_config || return 0
    show_nginx_config_detail "$selected_conf_file"
    read -rp "是否显示完整配置文件内容? [y/N]: " choice
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        echo "-------------------- $selected_conf_file --------------------"
        $SUDO sed -n '1,260p' "$selected_conf_file"
        echo "--------------------------------------------------------"
    fi
}

frontend_url_from_conf() {
    local file="$1"
    local domain port tls proto
    domain=$(conf_server_name "$file")
    port=$(conf_listen_port "$file")
    tls=$(conf_uses_tls "$file")
    proto=$([[ "$tls" == "yes" ]] && echo "https" || echo "http")

    if [[ -z "$domain" ]]; then
        return 1
    fi
    if [[ -n "$port" ]]; then
        echo "${proto}://${domain}:${port}"
    else
        echo "${proto}://${domain}"
    fi
}

reset_deploy_fields() {
    you_domain_full=""
    r_domain_full=""
    cert_domain=""
    manual_resolver=""
    parse_cert_domain="no"
    dns_provider=""
    domain_to_remove=""
    force_yes="${force_yes:-no}"
    template_domain_config_source=""
    no_proxy_redirect="no"
    target_conf_path=""
    skip_certificate_issue="no"
    ssl_certificate_path=""
    ssl_certificate_key_path=""

    you_domain=""
    you_domain_path=""
    you_frontend_port=""
    no_tls=""
    r_domain=""
    r_domain_path=""
    r_frontend_port=""
    r_http_frontend=""
}

prompt_optional_deploy_settings() {
    local input

    read -rp "是否配置高级选项（证书域名/DNS/重定向）? [y/N]: " input
    if [[ ! "$input" =~ ^[Yy]$ ]]; then
        if [[ "$skip_certificate_issue" == "yes" ]]; then
            log_info "使用默认选项：保留现有证书，启用 302/307 重定向代理。"
        else
            log_info "使用默认选项：访问域名申请证书，standalone 验证，启用 302/307 重定向代理。"
        fi
        return 0
    fi

    echo -e "${BLUE}--- 高级选项 ---${NC}"

    if [[ "$skip_certificate_issue" == "yes" ]]; then
        log_info "将保留现有证书路径，不重新申请证书。"
    else
        read -rp "证书主域名（留空则使用访问域名）: " input
        cert_domain="$input"

        read -rp "是否自动提取根域名申请泛域名证书? [y/N]: " input
        [[ "$input" =~ ^[Yy]$ ]] && parse_cert_domain="yes"

        read -rp "DNS 验证 provider（例如 cf，留空使用 standalone）: " input
        dns_provider="$input"
    fi

    read -rp "是否禁用 302/307 重定向代理? [y/N]: " input
    [[ "$input" =~ ^[Yy]$ ]] && no_proxy_redirect="yes"
}

run_deploy_flow() {
    setup_env
    prompt_interactive_mode
    display_summary
    if [[ "$dry_run" == "yes" ]]; then
        if ! command -v envsubst &>/dev/null; then
            log_error "dry-run 需要 envsubst，请先安装 gettext/gettext-base。"
            exit 1
        fi
        generate_nginx_config
        log_success "dry-run 完成，未写入文件、未申请证书、未重载 Nginx。"
        return 0
    fi

    install_dependencies
    generate_nginx_config
    if ! issue_certificate; then
        rollback_generated_config
        exit 1
    fi

    if test_and_reload_nginx; then
        log_success "部署成功！"
        local protocol
        protocol=$(get_protocol "$no_tls")
        echo -e "${GREEN}访问地址: ${protocol}://${you_domain}:${you_frontend_port}${you_domain_path}${NC}"
    else
        rollback_generated_config
        exit 1
    fi
}

add_nginx_config_menu() {
    local input_you input_r
    reset_deploy_fields
    echo -e "\n${BLUE}--- 新增反向代理配置 ---${NC}"
    echo "通常只需要填写下面两个地址，后续高级选项可直接回车跳过。"
    read -rp "访问地址 (例如 https://emby.example.com): " input_you
    read -rp "Emby 后端地址 (例如 http://127.0.0.1:8096): " input_r

    process_url_input "$input_you" "you"
    process_url_input "$input_r" "r"
    if [[ -z "$you_domain" || -z "$r_domain" ]]; then
        log_error "访问地址和后端地址不能为空，且建议使用完整 URL。"
        return 1
    fi
    prompt_optional_deploy_settings
    run_deploy_flow
}

edit_nginx_config_menu() {
    local current_you current_r input_you input_r current_domain new_domain cert key
    select_nginx_config || return 0
    show_nginx_config_detail "$selected_conf_file"

    current_you=$(frontend_url_from_conf "$selected_conf_file" || true)
    current_r=$(conf_proxy_target "$selected_conf_file")
    current_domain=$(conf_server_name "$selected_conf_file")
    cert=$(conf_ssl_cert_path "$selected_conf_file")
    key=$(conf_ssl_key_path "$selected_conf_file")

    if [[ -z "$current_you" || -z "$current_r" ]]; then
        log_error "该文件不是可自动修改的反向代理配置（缺少 server_name 或 proxy_pass）。"
        return 1
    fi

    echo -e "${YELLOW}修改会使用本脚本的 Emby 反代模板重写该配置文件。${NC}"
    read -rp "继续修改? [y/N]: " input_you
    [[ "$input_you" =~ ^[Yy]$ ]] || return 0

    reset_deploy_fields
    target_conf_path="$selected_conf_file"

    read -rp "前端访问地址 [$current_you]: " input_you
    input_you="${input_you:-$current_you}"
    read -rp "后端源站地址 [$current_r]: " input_r
    input_r="${input_r:-$current_r}"

    process_url_input "$input_you" "you"
    process_url_input "$input_r" "r"
    if [[ -z "$you_domain" || -z "$r_domain" ]]; then
        log_error "无法解析修改后的访问地址或后端地址。"
        return 1
    fi

    new_domain="$you_domain"
    if [[ "$new_domain" == "$current_domain" && -n "$cert" && -n "$key" ]]; then
        ssl_certificate_path="$cert"
        ssl_certificate_key_path="$key"
        skip_certificate_issue="yes"
    fi

    prompt_optional_deploy_settings
    run_deploy_flow
}

remove_nginx_config_menu() {
    select_nginx_config || return 0
    show_nginx_config_detail "$selected_conf_file"
    remove_conf_file="$selected_conf_file"
    remove_domain_config
    remove_conf_file=""
}

interactive_manage_menu() {
    local choice
    while true; do
        echo
        echo -e "${BLUE}========= Nginx 反代配置管理 =========${NC}"
        echo "1. 查看当前配置"
        echo "2. 新增反代配置"
        echo "3. 修改现有配置"
        echo "4. 删除现有配置"
        echo "0. 退出"
        echo "======================================"
        read -rp "请选择操作: " choice
        case "$choice" in
            1) view_nginx_configs_menu || true ;;
            2) add_nginx_config_menu || true ;;
            3) edit_nginx_config_menu || true ;;
            4) remove_nginx_config_menu || true ;;
            0) exit 0 ;;
            *) log_warn "无效选项，请重新选择。" ;;
        esac
    done
}

# ===================================================================================
#                                 核心逻辑
# ===================================================================================

# --- 1. 参数解析 ---
parse_arguments() {
    you_domain_full=""
    r_domain_full=""
    cert_domain=""
    manual_resolver=""
    parse_cert_domain="no"
    dns_provider=""
    domain_to_remove=""
    force_yes="no"
    template_domain_config_source=""
    no_proxy_redirect="no"
    manual_gh_proxy=""
    manage_menu="no"
    list_configs="no"
    dry_run="no"
    target_conf_path=""
    skip_certificate_issue="no"
    ssl_certificate_path=""
    ssl_certificate_key_path=""

    you_domain=""; you_domain_path=""; you_frontend_port=""; no_tls=""
    r_domain=""; r_domain_path=""; r_frontend_port=""; r_http_frontend=""

    local TEMP
    if ! TEMP=$(getopt -o y:r:m:R:dD:hYc: --long you-domain:,r-domain:,cert-domain:,resolver:,parse-cert-domain,dns:,gh-proxy:,remove:,yes,template-domain-config:,no-proxy-redirect,menu,list,dry-run,help -n "$(basename "$0")" -- "$@"); then
        exit 1
    fi
    eval set -- "$TEMP"
    unset TEMP

    while true; do
        case "$1" in
            -y|--you-domain) you_domain_full="$2"; shift 2 ;;
            -r|--r-domain) r_domain_full="$2"; shift 2 ;;
            -m|--cert-domain) cert_domain="$2"; shift 2 ;;
            -d|--parse-cert-domain) parse_cert_domain="yes"; shift ;;
            -D|--dns) dns_provider="$2"; shift 2 ;;
            -R|--resolver) manual_resolver="$2"; shift 2 ;;
            -c|--template-domain-config) template_domain_config_source="$2"; shift 2 ;;
            --no-proxy-redirect) no_proxy_redirect="yes"; shift ;;
            --gh-proxy) manual_gh_proxy="$2"; shift 2 ;;
            --remove) domain_to_remove="$2"; shift 2 ;;
            -Y|--yes) force_yes="yes"; shift ;;
            --menu) manage_menu="yes"; shift ;;
            --list) list_configs="yes"; shift ;;
            --dry-run) dry_run="yes"; shift ;;
            -h|--help) show_help; shift ;;
            --) shift; break ;;
            *) log_error "未知参数 $1"; exit 1 ;;
        esac
    done

    process_url_input "$you_domain_full" "you"
    process_url_input "$r_domain_full" "r"
}

# --- 2. 交互模式 ---
prompt_interactive_mode() {
    if [[ -z "$you_domain" || -z "$r_domain" ]]; then
        if [ ! -t 0 ]; then
            log_error "无法进入交互模式。请提供 -y 和 -r 参数。"
            exit 1
        fi

        echo -e "\n${BLUE}--- 交互模式: 配置反向代理 ---${NC}"
        read -rp "请输入要访问的地址 (本机的公网IP或者域名,例如 https://11.22.33.44:8888 或 https://emby.mysite.com): " input_you
        read -rp "请输入要反代的 Emby 地址 (原本的 Emby 访问链接, 例如 https://emby.server.com): " input_r

        process_url_input "$input_you" "you"
        process_url_input "$input_r" "r"

        if [[ -z "$you_domain" || -z "$r_domain" ]]; then
            log_error "域名信息不能为空。"
            exit 1
        fi
    fi
}

# --- 3. 显示摘要 ---
display_summary() {
    # 确定证书域名：IP > 手动指定 > 自动解析 > 默认
    if is_ip_address "$you_domain"; then
        format_cert_domain="${you_domain//[\[\]]/}"
        if [[ "$no_tls" != "yes" ]]; then
            log_info "检测到 IP 地址 (含 IPv6)，将申请 Let's Encrypt short-lived (短期) 证书。"
        fi
    elif [[ -n "$cert_domain" ]]; then
        format_cert_domain="$cert_domain"
    elif [[ "$parse_cert_domain" == "yes" && "$you_domain" == *.*.* ]]; then
        format_cert_domain="${you_domain#*.}"
        else
        format_cert_domain="${cert_domain:-$you_domain}"
    fi

    # 确定解析器
    if [[ -n "$manual_resolver" ]]; then
        resolver="$manual_resolver valid=60s"
    else
        # 修正: has_ipv6 返回 exit code, 不输出文本
        local ipv6_flag=$(has_ipv6 && echo "" || echo "ipv6=off")
        resolver="$(printf '%s %s' "$(get_resolver_host)" "$ipv6_flag" | xargs)"
    fi

    local protocol=$(get_protocol "$no_tls")
    local r_protocol=$(get_protocol "$r_http_frontend")

    echo -e "\n${BLUE}🔧 Nginx 反代配置摘要${NC}"
    echo "──────────────────────────────────────────────"
    echo -e "➡️  前端访问: ${GREEN}${protocol}://${you_domain}:${you_frontend_port}${you_domain_path}${NC}"
    echo -e "⬅️  后端源站: ${YELLOW}${r_protocol}://${r_domain}:${r_frontend_port}${r_domain_path}${NC}"
    echo "──────────────────────────────────────────────"
    echo -e "📜 证书域名: ${format_cert_domain}"
    echo -e "🔒 TLS 状态: $([[ "$no_tls" == "yes" ]] && echo "${RED}禁用 (HTTP Only)${NC}" || echo "${GREEN}启用 (HTTPS)${NC}")"
    echo -e "🧠 DNS 解析: ${resolver}"
    echo -e "🔄 302/307 代理: $([[ "$no_proxy_redirect" == "yes" ]] && echo "${RED}禁用${NC}" || echo "${GREEN}启用${NC}")"
    echo -e "🌏 配置文件源: ${CONF_HOME}"
    echo "──────────────────────────────────────────────"
}

# --- 4. 依赖安装 ---
install_dependencies() {
    local OS_NAME PM GNUPG_PM

    if [ -f /etc/os-release ]; then
        source /etc/os-release
    else
        log_error "无法读取 /etc/os-release，不支持的系统。"
        exit 1
    fi

    # 严格按照原版 deploy.sh 的 case 逻辑，确保变量赋值一致
    case "$ID" in
      debian|devuan|kali) OS_NAME='debian'; PM='apt-get'; GNUPG_PM='gnupg2' ;;
      ubuntu) OS_NAME='ubuntu'; PM='apt-get'; GNUPG_PM=$([[ ${VERSION_ID%%.*} -lt 22 ]] && echo "gnupg2" || echo "gnupg") ;;
      centos|fedora|rhel|almalinux|rocky|amzn) OS_NAME='rhel'; PM=$(command -v dnf >/dev/null && echo "dnf" || echo "yum") ;;
      arch|archarm) OS_NAME='arch'; PM='pacman' ;;
      alpine) OS_NAME='alpine'; PM='apk' ;;
      *) echo "错误: 不支持的操作系统 '$ID'。" >&2; exit 1 ;;
    esac

    log_info "检查 Nginx..."
    if ! command -v nginx &> /dev/null; then
        log_info "Nginx 未安装，正在从官方源为 '$OS_NAME' 安装..."

        case "$OS_NAME" in
          debian|ubuntu)
              $SUDO "$PM" update
              $SUDO "$PM" install -y "$GNUPG_PM" ca-certificates lsb-release "${OS_NAME}-keyring"
              curl -sL https://nginx.org/keys/nginx_signing.key | $SUDO gpg --dearmor -o /usr/share/keyrings/nginx-archive-keyring.gpg
              echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/mainline/$OS_NAME `lsb_release -cs` nginx" | $SUDO tee /etc/apt/sources.list.d/nginx.list > /dev/null
              echo -e "Package: *\nPin: origin nginx.org\nPin: release o=nginx\nPin-Priority: 900" | $SUDO tee /etc/apt/preferences.d/99nginx > /dev/null
              $SUDO "$PM" update
              $SUDO "$PM" install -y nginx
              $SUDO mkdir -p /etc/systemd/system/nginx.service.d
              echo -e "[Service]\nExecStartPost=/bin/sleep 0.1" | $SUDO tee /etc/systemd/system/nginx.service.d/override.conf > /dev/null
              $SUDO systemctl daemon-reload
              $SUDO systemctl restart nginx
              ;;
          rhel)
              $SUDO "$PM" install -y yum-utils
              echo -e "[nginx-mainline]\nname=NGINX Mainline Repository\nbaseurl=https://nginx.org/packages/mainline/centos/\$releasever/\$basearch/\ngpgcheck=1\nenabled=1\ngpgkey=https://nginx.org/keys/nginx_signing.key" | $SUDO tee /etc/yum.repos.d/nginx.repo > /dev/null
              $SUDO "$PM" install -y nginx
              $SUDO mkdir -p /etc/systemd/system/nginx.service.d
              echo -e "[Service]\nExecStartPost=/bin/sleep 0.1" | $SUDO tee /etc/systemd/system/nginx.service.d/override.conf > /dev/null
              $SUDO systemctl daemon-reload
              $SUDO systemctl restart nginx
              ;;
          arch)
              $SUDO "$PM" -Sy --noconfirm nginx-mainline
              $SUDO mkdir -p /etc/systemd/system/nginx.service.d
              echo -e "[Service]\nExecStartPost=/bin/sleep 0.1" | $SUDO tee /etc/systemd/system/nginx.service.d/override.conf > /dev/null
              $SUDO systemctl daemon-reload
              $SUDO systemctl restart nginx
              ;;
          alpine)
              $SUDO "$PM" update
              $SUDO "$PM" add --no-cache nginx
              $SUDO rc-update add nginx default
              $SUDO rc-service nginx restart
              ;;
        esac
        log_success "Nginx 安装完成。"
    else
        log_info "Nginx 已安装。"
    fi

    # 补充安装依赖工具 (socat 等)
    if ! command -v socat &>/dev/null; then
        log_info "安装 socat 等辅助工具..."
        case "$OS_NAME" in
            debian|ubuntu) $SUDO "$PM" install -y socat ;;
            arch) $SUDO "$PM" -S --noconfirm socat ;;
            alpine) $SUDO "$PM" add --no-cache socat ;;
            *) $SUDO "$PM" install -y socat ;;
        esac
    fi

    if ! command -v envsubst &>/dev/null; then
        log_info "检测到 envsubst 缺失，正在安装 gettext..."
        case "$OS_NAME" in
            debian|ubuntu) $SUDO "$PM" install -y gettext-base ;;
            arch) $SUDO "$PM" -S --noconfirm gettext ;;
            alpine) $SUDO "$PM" add --no-cache gettext ;;
            *) $SUDO "$PM" install -y gettext ;;
        esac
    fi

    if ! command -v crontab &>/dev/null; then
        log_info "检测到 crontab 缺失，正在安装 cron..."
        case "$OS_NAME" in
            debian|ubuntu) $SUDO "$PM" install -y cron ;;
            rhel) $SUDO "$PM" install -y cronie ;;
            arch) $SUDO "$PM" -S --noconfirm cronie ;;
            alpine) $SUDO "$PM" add --no-cache dcron ;;
        esac
    fi

    # acme.sh 安装逻辑
    ACME_SH="$HOME/.acme.sh/acme.sh"
    if [[ "$no_tls" != "yes" && "$skip_certificate_issue" != "yes" && ! -f "$ACME_SH" ]]; then
       log_info "正在为当前用户安装 acme.sh... (URL: $ACME_INSTALL_URL)"
       local TMP_INSTALL_SCRIPT="./acme.sh"
       trap "rm -f '$TMP_INSTALL_SCRIPT'" RETURN

       if download_with_verify "$ACME_INSTALL_URL" "$TMP_INSTALL_SCRIPT" "acme.sh"; then
           if sh "$TMP_INSTALL_SCRIPT" --install-online; then
               log_success "acme.sh 安装完成。"
               "$ACME_SH" --upgrade --auto-upgrade
               "$ACME_SH" --set-default-ca --server letsencrypt
           else
               log_error "acme.sh 安装脚本执行失败。"
               exit 1
           fi
       else
           exit 1
       fi
    fi
}

# --- 获取模板内容 ---
get_template_content() {
    if [[ -n "$template_domain_config_source" ]]; then
        if [[ "$template_domain_config_source" == http* ]]; then
            curl -fsL "$template_domain_config_source"
        elif [ -f "$template_domain_config_source" ]; then
            cat "$template_domain_config_source"
        else
            log_error "指定的模板无效。"
            return 1
        fi
    else
        local tpl_name=$([[ "$no_tls" == "yes" ]] && echo "p.example.com.no_tls.conf" || echo "p.example.com.conf")
        local local_tpl
        local_tpl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/conf.d/$tpl_name"
        if [ -f "$local_tpl" ]; then
            log_info "使用本地模板: $local_tpl"
            cat "$local_tpl"
        else
            log_info "下载模板: $tpl_name (源: $CONF_HOME/conf.d/$tpl_name)..."
            curl -fsL "$CONF_HOME/conf.d/$tpl_name"
        fi
    fi
}

# --- 5. 生成配置 ---
generate_nginx_config() {
    log_info "准备生成 Nginx 配置文件..."

    local main_conf="/etc/nginx/nginx.conf"
    if [ ! -f "$main_conf" ]; then
        log_error "未找到 $main_conf。请先安装并初始化 nginx。"
        exit 1
    fi

    if ! grep -Eq 'include[[:space:]]+/etc/nginx/conf\.d/\*\.conf;' "$main_conf"; then
        log_error "当前 $main_conf 未包含 /etc/nginx/conf.d/*.conf，脚本不会接管主配置。"
        log_error "请先手动把 conf.d include 接入现有 nginx，然后重新运行脚本。"
        exit 1
    fi

    local template_content
    template_content=$(get_template_content) || exit 1
    [[ -z "$template_content" ]] && { log_error "获取配置模板失败。"; exit 1; }
    if ! printf '%s\n' "$template_content" | grep -Eq '^[[:space:]]*server[[:space:]]*\{'; then
        log_error "配置模板内容无效，未找到 server 块。"
        exit 1
    fi

    export you_domain_path_rewrite=""
    if [[ -n "$you_domain_path" && "$you_domain_path" != "/" ]]; then
        local target_path source_path_regex target_path_replacement
        target_path=$(normalize_url_path "${r_domain_path:-/}") || {
            log_error "后端 URL path 包含 Nginx 配置不支持的字符: ${r_domain_path:-/}"
            exit 1
        }
        source_path_regex=$(escape_nginx_regex_literal "$you_domain_path")
        if [[ "$target_path" == "/" ]]; then
            target_path_replacement=""
        else
            target_path_replacement=$(escape_nginx_rewrite_replacement "$target_path")
        fi
        export you_domain_path_rewrite="rewrite ^${source_path_regex}(?:/(.*))?\$ ${target_path_replacement}/\$1 break;"
    fi

    if [[ -z "$ssl_certificate_path" ]]; then
        ssl_certificate_path="/etc/nginx/certs/$format_cert_domain/cert"
    fi
    if [[ -z "$ssl_certificate_key_path" ]]; then
        ssl_certificate_key_path="/etc/nginx/certs/$format_cert_domain/key"
    fi

    export you_domain you_frontend_port resolver format_cert_domain ssl_certificate_path ssl_certificate_key_path
    export acme_http_webroot="${ACME_HTTP_WEBROOT:-/usr/share/nginx/html}"
    export you_domain_path="${you_domain_path:-/}"

    local r_proto=$(get_protocol "$r_http_frontend")
    local r_port_str=$([[ -n "$r_frontend_port" ]] && echo ":$r_frontend_port" || echo "")
    export r_domain_full="${r_proto}://${r_domain}${r_port_str}"

    # 根据 no_proxy_redirect 设置生成配置
    if [[ "$no_proxy_redirect" == "yes" ]]; then
        # 禁用 302/307 代理
        export location_proxy_redirect='        # proxy_redirect disabled - passing redirects directly to client'
        export backstream_config=''
        export handle_redirect_config=''
    else
        # 启用 302/307 代理（默认）
export location_proxy_redirect='        proxy_redirect ~^(https?)://([^:/]+(?::[0-9]+)?)(/.+)$ $scheme://$server_name:$server_port/backstream/$1/$2$3;

        proxy_intercept_errors on;
        error_page 307 = @handle_redirect;'
        export backstream_config='    location ~  ^/backstream/(https?)/([^/]+)  {
        set $website                          $1://$2;
        rewrite ^/backstream/(https?)/([^/]+)(/.+)$  $3 break;
        early_hints $early_hints;
        proxy_pass                            $website; #如果重定向的地址是http这里需要替换为http

        proxy_set_header Host                 $proxy_host;
        proxy_set_header X-Real-IP            $remote_addr;
        proxy_set_header X-Forwarded-For      $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto    $scheme;
        proxy_set_header X-Forwarded-Host     $host;
        proxy_set_header X-Forwarded-Port     $server_port;

        proxy_http_version                    1.1;
        proxy_cache_bypass                    $http_upgrade;
        proxy_ssl_server_name                 on;

        proxy_set_header Upgrade              $http_upgrade;
        proxy_set_header Connection           $connection_upgrade;

        proxy_connect_timeout                 60s;
        proxy_send_timeout                    1h;
        proxy_read_timeout                    1h;

        proxy_redirect ~^(https?)://([^:/]+(?::[0-9]+)?)(/.+)$ $scheme://$server_name:$server_port/backstream/$1/$2$3;
        set $rediret_scheme $1;
        set $rediret_host $2;
        sub_filter                            $proxy_host $host;
        sub_filter '"'"'$rediret_scheme://$rediret_host'"'"' '"'"'$scheme://$server_name:$server_port/backstream/$rediret_scheme/$rediret_host'"'"';
        sub_filter_once                       off;
    }

'
        export handle_redirect_config='    location @handle_redirect {
        set $saved_redirect_location '"'"'$upstream_http_location'"'"';
        early_hints $early_hints;
        proxy_pass $saved_redirect_location;
        proxy_set_header Host                 $proxy_host;
        proxy_set_header X-Real-IP            $remote_addr;
        proxy_set_header X-Forwarded-For      $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto    $scheme;
        proxy_set_header X-Forwarded-Host     $host;
        proxy_set_header X-Forwarded-Port     $server_port;
        proxy_http_version                    1.1;
        proxy_cache_bypass                    $http_upgrade;

        proxy_ssl_server_name                 on;

        proxy_set_header Upgrade              $http_upgrade;
        proxy_set_header Connection           $connection_upgrade;

        proxy_connect_timeout                 60s;
        proxy_send_timeout                    1h;
        proxy_read_timeout                    1h;
      
    }

'
    fi

    local vars='$you_domain $you_frontend_port $resolver $format_cert_domain $ssl_certificate_path $ssl_certificate_key_path $acme_http_webroot $you_domain_path $you_domain_path_rewrite $r_domain_full $location_proxy_redirect $backstream_config $handle_redirect_config'

    local clean_you_domain="${you_domain//[\[\]]/}"
    local conf_path conflict_path
    if [[ -n "$target_conf_path" ]]; then
        conf_path="$target_conf_path"
        if ! conf_is_managed_emby_config "$conf_path"; then
            log_error "拒绝覆盖未由本脚本管理的配置文件: $conf_path"
            exit 1
        fi
    else
        conf_path=$(find_nginx_conf_file "$you_domain" "$you_frontend_port" || true)
        if [[ -z "$conf_path" ]]; then
            conflict_path=$(find_any_nginx_conf_file "$you_domain" "$you_frontend_port" || true)
            if [[ -n "$conflict_path" ]]; then
                log_error "已存在同域名/端口的非脚本管理配置: $conflict_path"
                log_error "为避免覆盖现有 Nginx 配置，请先手动迁移或换一个域名/端口。"
                exit 1
            fi
            conf_path=$(default_nginx_conf_path "$clean_you_domain" "$you_frontend_port")
        fi
    fi

    local rendered_config
    rendered_config=$({
        echo "# managed_by=nginx-reverse-emby-deploy"
        echo "# nre_emby_managed=true"
        echo "# domain=$you_domain"
        echo "# https_enabled=$([[ "$no_tls" == "yes" ]] && echo "false" || echo "true")"
        echo "# listen_port=$you_frontend_port"
        echo "# backend=$r_domain_full"
        echo
        echo "$template_content" | envsubst "$vars"
    })

    if [[ "$dry_run" == "yes" ]]; then
        echo
        echo "-------------------- dry-run: $conf_path --------------------"
        printf '%s\n' "$rendered_config"
        echo "--------------------------------------------------------------"
        return 0
    fi

    generated_conf_path="$conf_path"
    backup_file "$conf_path"
    printf '%s\n' "$rendered_config" | $SUDO tee "$conf_path" > /dev/null
    log_success "配置文件已生成: $conf_path"
}

# --- 6. 证书申请 ---
issue_certificate() {
    if [[ "$no_tls" == "yes" ]]; then
        log_info "检测到非 TLS 配置，跳过证书申请步骤。"
        return
    fi

    if [[ "$skip_certificate_issue" == "yes" ]]; then
        log_info "检测到现有证书路径，修改配置时跳过证书申请。"
        return
    fi

    ACME_SH="$HOME/.acme.sh/acme.sh"
    if [[ ! -f "$ACME_SH" ]]; then
        log_error "未找到 acme.sh，请先完成依赖安装。"
        return 1
    fi

    # 直接使用 format_cert_domain (无括号) 构建路径
    local cert_path_base="/etc/nginx/certs/$format_cert_domain"
    local reload_cmd="$SUDO nginx -s reload"

    local issue_extra_args=()

    # 针对 IP 证书 (含 IPv6) 的特殊处理
    local is_ip=false

    if is_ip_address "$you_domain"; then
        is_ip=true
        log_info "检测到 IP 地址，将配置为 short-lived (短期) 证书模式..."
        [[ -n "$dns_provider" ]] && { log_warn "IP 证书不支持 DNS 验证，已自动切换为 Standalone 模式。"; dns_provider=""; }
        issue_extra_args=(--certificate-profile shortlived --days 6)
    fi

    # 检查证书是否已存在 (使用 format_cert_domain 查询)
    if ! acme_cert_is_issued "$format_cert_domain"; then
        log_info "证书不存在，开始申请..."
        $SUDO mkdir -p "$cert_path_base"
        cleanup_stale_acme_record "$format_cert_domain"

        if [[ -n "$dns_provider" ]]; then
            if ! issue_certificate_dns; then
                cleanup_stale_acme_record "$format_cert_domain"
                return 1
            fi
        elif should_use_webroot_http01 "$is_ip"; then
            if ! issue_certificate_webroot; then
                cleanup_stale_acme_record "$format_cert_domain"
                return 1
            fi
        else
            if ! issue_certificate_standalone "$is_ip"; then
                cleanup_stale_acme_record "$format_cert_domain"
                return 1
            fi
        fi
        log_success "证书申请成功。"
    else
        log_info "证书已由 acme.sh 管理，将跳过申请步骤，直接进行安装/更新。"
    fi

    # 安装证书
    $SUDO mkdir -p "$cert_path_base"
    log_info "正在安装证书到 Nginx 目录..."
    # 使用 format_cert_domain (无括号) 安装
    if ! "$ACME_SH" --install-cert -d "$format_cert_domain" --ecc \
        --fullchain-file "$cert_path_base/cert" \
        --key-file "$cert_path_base/key" \
        --reloadcmd "$reload_cmd"; then
        log_error "证书安装失败。"
        return 1
    fi

    log_success "证书安装并部署完成。"
    return 0
}

# --- 证书申请：DNS 模式 ---
issue_certificate_dns() {
    local dns_arg="dns_${dns_provider}"
    local domain_args=(-d "$format_cert_domain")

    # 泛域名逻辑：如果不是 IP 且与 you_domain 不同，则补充 *.domain。
    if [[ "$format_cert_domain" != "$you_domain" ]] && ! is_ip_address "$you_domain"; then
        domain_args+=(-d "*.$format_cert_domain")
    fi

    log_info "使用 DNS 模式 ($dns_provider) 申请证书..."
    if "$ACME_SH" --issue --dns "$dns_arg" "${domain_args[@]}" --keylength ec-256; then
        return 0
    fi

    log_warn "DNS 申请首次失败，清理残留状态后使用 --force 重试一次..."
    cleanup_stale_acme_record "$format_cert_domain"
    if ! "$ACME_SH" --issue --force --dns "$dns_arg" "${domain_args[@]}" --keylength ec-256; then
        log_error "证书申请失败（重试后仍失败）。"
        return 1
    fi
    return 0
}

should_use_webroot_http01() {
    local is_ip_mode="$1"

    [[ "$is_ip_mode" == "true" ]] && return 1
    [[ "$format_cert_domain" != "$you_domain" ]] && return 1
    command -v ss >/dev/null || return 1
    pgrep -x nginx >/dev/null || return 1
    ss -ltn '( sport = :80 )' | grep -q LISTEN
}

reload_nginx_quietly() {
    if pgrep -x nginx >/dev/null; then
        $SUDO nginx -s reload
    elif command -v systemctl >/dev/null; then
        $SUDO systemctl restart nginx
    else
        $SUDO rc-service nginx restart
    fi
}

issue_certificate_webroot() {
    local webroot="${ACME_HTTP_WEBROOT:-/usr/share/nginx/html}"
    local conf_dir challenge_conf pending_conf safe_name issue_status=1
    local restored_backup="no"

    conf_dir=$(get_nginx_conf_dir)
    safe_name=$(printf '%s' "$format_cert_domain" | tr -c 'A-Za-z0-9_.-' '_')
    challenge_conf="$conf_dir/nre-acme-${safe_name}-80.conf"
    pending_conf="${generated_conf_path}.acme-pending.$$"

    log_info "检测到 Nginx 正在监听 80 端口，改用 webroot 模式申请证书。"
    $SUDO mkdir -p "$webroot/.well-known/acme-challenge"

    if [[ -n "${generated_conf_path:-}" && -f "$generated_conf_path" ]]; then
        $SUDO mv "$generated_conf_path" "$pending_conf"
        if [[ -n "${last_backup_path:-}" && -f "$last_backup_path" ]]; then
            $SUDO cp "$last_backup_path" "$generated_conf_path"
            restored_backup="yes"
        fi
    fi

    {
        echo "# temporary ACME HTTP-01 challenge for $format_cert_domain"
        echo "server {"
        echo "    listen 80;"
        echo "    listen [::]:80;"
        echo "    server_name $format_cert_domain;"
        echo
        echo "    location ^~ /.well-known/acme-challenge/ {"
        echo "        root $webroot;"
        echo "        default_type text/plain;"
        echo "        try_files \$uri =404;"
        echo "    }"
        echo
        echo "    location / {"
        echo "        return 404;"
        echo "    }"
        echo "}"
    } | $SUDO tee "$challenge_conf" > /dev/null

    if $SUDO nginx -t && reload_nginx_quietly; then
        if "$ACME_SH" --issue --webroot "$webroot" -d "$format_cert_domain" --keylength ec-256 "${issue_extra_args[@]}"; then
            issue_status=0
        fi
    else
        log_error "临时 ACME challenge 配置无法通过 Nginx 测试。"
    fi

    $SUDO rm -f "$challenge_conf"
    if $SUDO nginx -t; then
        reload_nginx_quietly || true
    fi

    if [[ -n "$pending_conf" && -f "$pending_conf" ]]; then
        if [[ "$restored_backup" == "yes" ]]; then
            $SUDO rm -f "$generated_conf_path"
        fi
        $SUDO mv "$pending_conf" "$generated_conf_path"
    fi

    if [[ "$issue_status" -ne 0 ]]; then
        log_error "webroot 模式证书申请失败。"
        return 1
    fi
    return 0
}

# --- 证书申请：Standalone 模式 (支持 IPv6) ---
issue_certificate_standalone() {
    local is_ip_mode="$1"

    # 泛域名检查：如果不是 IP，且 format_cert_domain 不等于 you_domain (说明是 *.xxx)，则不能用 standalone
    if [[ "$is_ip_mode" != "true" && "$format_cert_domain" != "$you_domain" ]]; then
        log_error "泛域名证书必须使用 DNS 模式申请。"
        return 1
    fi

    log_info "使用 Standalone 模式申请证书..."

    # 针对 IPv6，acme.sh 需要额外监听参数
    local listen_args=()

    if [[ "$is_ip_mode" == "true" ]]; then
        # 针对 IPv6 添加 --listen-v6
        if [[ "$you_domain" =~ : ]]; then
            listen_args=(--listen-v6)
            log_info "检测到 IPv6 地址，添加 --listen-v6 参数..."
        fi
    fi

    # 使用 format_cert_domain (无括号) 进行申请
    if "$ACME_SH" --issue --standalone -d "$format_cert_domain" --keylength ec-256 "${issue_extra_args[@]}" "${listen_args[@]}"; then
        return 0
    fi

    log_warn "Standalone 申请首次失败，清理残留状态后使用 --force 重试一次..."
    cleanup_stale_acme_record "$format_cert_domain"
    if ! "$ACME_SH" --issue --force --standalone -d "$format_cert_domain" --keylength ec-256 "${issue_extra_args[@]}" "${listen_args[@]}"; then
        log_error "证书申请失败（重试后仍失败）。请检查域名/IP解析是否正确，或防火墙是否放行 80 端口。"
        return 1
    fi

    return 0
}

# --- 7. 移除配置 ---
remove_domain_config() {
    local remove_url="$domain_to_remove"
    local domain port temp_path temp_proto nginx_conf_file

    if [[ -n "${remove_conf_file:-}" ]]; then
        nginx_conf_file="$remove_conf_file"
        domain=$(conf_server_name "$nginx_conf_file")
        port=$(conf_listen_port "$nginx_conf_file")
        temp_proto=$([[ "$(conf_uses_tls "$nginx_conf_file")" == "yes" ]] && echo "https" || echo "http")
        log_info "准备移除选中的配置文件: $nginx_conf_file"
    else
        log_info "正在为 '$remove_url' 查找相关配置..."

        # 精确解析域名和端口
        # 注意：parse_url 返回格式为 proto|domain|port|path
        IFS='|' read -r temp_proto domain port temp_path < <(parse_url "$remove_url")

        # 兼容无协议输入: example.com 或 [IPv6]
        if [[ -z "$domain" && -n "$temp_proto" && "$temp_proto" != "http" && "$temp_proto" != "https" ]]; then
            domain="$temp_proto"
            temp_proto=""
        fi

        if [[ -z "$domain" ]]; then
            log_error "无法解析待移除域名，请使用完整 URL（如 https://example.com:443）。"
            exit 1
        fi

        # 如果未解析出协议，则假定为 https
        if [[ -z "$temp_proto" ]]; then
            temp_proto="https"
        fi

        # 根据协议决定默认端口
        if [[ "$temp_proto" == "https" ]]; then
            port="${port:-443}"
        else
            port="${port:-80}"
        fi

        nginx_conf_file=$(find_nginx_conf_file "$domain" "$port" || true)
    fi

    if ! $SUDO [ -f "$nginx_conf_file" ]; then
        log_error "未找到与 '$domain' 在端口 '$port' 上的 Nginx 配置文件。"
        # 找不到文件时，不强制退出，可能用户只是想清理残留证书，或者文件已经被删了一部分
        # return 1
        # 但为了逻辑严谨，若连配置文件都没有，后续的逻辑依据也没了，这里还是退出比较好。
        exit 1
    fi

    # 智能判断是否使用 TLS
    local uses_tls="no"
    local remove_cert_domain=""
    local cert_dir=""
    local cert_full_path=""
    local cert_shared="no"

    if $SUDO grep -q "ssl_certificate" "$nginx_conf_file"; then
        uses_tls="yes"
        # 从 Nginx 配置中直接推断证书域名
        cert_full_path=$($SUDO awk "/ssl_certificate / {print \$2}" "$nginx_conf_file" | head -n 1 | sed 's/;//')
        if [[ -z "$cert_full_path" ]]; then
            log_warn "无法从配置中解析证书路径，将跳过证书删除，仅移除站点配置。"
            cert_shared="yes"
        else
            local cert_parent_dir
            cert_parent_dir=$(dirname "$cert_full_path")
            remove_cert_domain=$(basename "$cert_parent_dir")
            cert_dir="/etc/nginx/certs/$remove_cert_domain"

            # 精确判断是否共享证书: 是否被其他 conf 引用
            local current_conf_basename
            current_conf_basename=$(basename "$nginx_conf_file")
            local other_refs
            other_refs=$($SUDO grep -Rsl -F "$cert_full_path" /etc/nginx/conf.d --exclude="$current_conf_basename" 2>/dev/null || true)
            if [[ -n "$other_refs" ]]; then
                cert_shared="yes"
            fi
        fi
    fi

    echo "--------------------------------------------------------"
    echo -e "${RED}警告: 即将执行破坏性操作！${NC}"
    echo "将要为 '$domain' (端口: $port) 移除以下内容:"
    echo "  - Nginx 配置文件: $nginx_conf_file"

    if [[ "$uses_tls" == "yes" ]]; then
        if [[ "$cert_shared" == "no" ]]; then
            if $SUDO [ -d "$cert_dir" ]; then
                echo "  - Nginx 证书目录: $cert_dir"
            fi
            ACME_SH="$HOME/.acme.sh/acme.sh"
            if [[ -n "$remove_cert_domain" && -f "$ACME_SH" ]]; then
                 echo "  - acme.sh 证书记录 (针对域名: $remove_cert_domain)"
            fi
        else
            echo -e "${YELLOW}  - 注意: 检测到共享证书 ($remove_cert_domain)，已被其他站点配置引用，将不会删除证书文件。${NC}"
        fi
    fi
    echo "--------------------------------------------------------"

    # [修正] 智能确认流程
    if [ ! -t 0 ]; then # 非交互模式
        if [[ "$force_yes" != "yes" ]]; then
            log_error "在非交互模式下，移除操作必须使用 '-Y' 或 '--yes' 参数进行确认。"
            exit 1
        fi
        log_info "检测到 '--yes' 参数，将自动执行移除操作。"
    else # 交互模式
        if [[ "$force_yes" != "yes" ]]; then
            read -rp "此操作不可逆，请输入 'yes' 确认移除: " confirmation
            if [[ "$confirmation" != "yes" ]]; then
                log_info "操作已取消。"
                if [[ -n "${remove_conf_file:-}" ]]; then
                    return 0
                fi
                exit 0
            fi
        fi
    fi

    log_info "开始移除..."
    local remove_backup_path=""
    backup_file "$nginx_conf_file"
    remove_backup_path="$last_backup_path"

    $SUDO rm -f "$nginx_conf_file"
    log_info "Nginx 配置文件已临时移除。"

    log_info "正在检查 Nginx 配置并执行重载..."
    if ! test_and_reload_nginx; then
        log_error "Nginx 配置测试失败，正在恢复移除前的配置。"
        if [[ -n "$remove_backup_path" && -f "$remove_backup_path" ]]; then
            $SUDO cp "$remove_backup_path" "$nginx_conf_file"
            log_warn "已恢复配置文件: $nginx_conf_file"
            if test_and_reload_nginx; then
                log_warn "已恢复移除前的 Nginx 配置，本次删除未生效。"
            else
                log_error "恢复配置后 Nginx 仍无法通过测试，请手动检查: $nginx_conf_file"
            fi
        else
            log_error "未找到可恢复的配置备份。"
        fi
        return 1
    fi

    log_info "Nginx 已加载移除后的配置。"

    if [[ "$uses_tls" == "yes" ]]; then
        if [[ "$cert_shared" == "no" ]]; then
            if $SUDO [ -d "$cert_dir" ]; then
                $SUDO rm -rf "$cert_dir"
                log_info "Nginx 证书目录已删除。"
            fi

            ACME_SH="$HOME/.acme.sh/acme.sh"
            if [[ -n "$remove_cert_domain" && -f "$ACME_SH" ]]; then
                # 优先删除 ECC 记录，失败再尝试默认类型，避免遗留
                if "$ACME_SH" --remove -d "$remove_cert_domain" --ecc >/dev/null 2>&1 || \
                   "$ACME_SH" --remove -d "$remove_cert_domain" >/dev/null 2>&1; then
                    log_info "acme.sh 证书记录已移除。"
                else
                    log_warn "从 acme.sh 移除证书失败，可能记录已不存在。"
                fi
            fi
        else
            log_info "证书目录和 acme.sh 记录未被删除。"
            echo "如果确认其他站点已不再引用此证书，请手动执行以下命令清理："
            echo "  $HOME/.acme.sh/acme.sh --remove -d '$remove_cert_domain' --ecc"
            echo "  $SUDO rm -rf '$cert_dir'"
        fi
    fi

    log_success "域名 '$domain' 的相关配置已成功移除！"
}

# ===================================================================================
#                                 主流程
# ===================================================================================

test_and_reload_nginx() {
    log_info "测试 Nginx 配置..."
    if $SUDO nginx -t; then
        # 增加判断，如果 nginx 没运行，尝试启动而不是 reload
        if pgrep -x "nginx" >/dev/null; then
            $SUDO nginx -s reload
        else
            if command -v systemctl >/dev/null; then
                $SUDO systemctl restart nginx
            else
                $SUDO rc-service nginx restart
            fi
        fi
        return 0
    else
        log_error "Nginx 配置测试失败。"
        return 1
    fi
}

main() {
    local arg_count=$#
    parse_arguments "$@"

    if [[ "$list_configs" == "yes" ]]; then
        list_nginx_configs
        exit 0
    fi

    if [[ "$manage_menu" == "yes" ]] || { [[ "$arg_count" -eq 0 ]] && [ -t 0 ]; }; then
        interactive_manage_menu
        exit 0
    fi

    if [[ -n "$domain_to_remove" ]]; then
        remove_domain_config
        exit 0
    fi

    run_deploy_flow
}

main "$@"
