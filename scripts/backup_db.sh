#!/bin/bash
# Đường dẫn lưu file backup
BACKUP_DIR="/var/backups/postgres_django"
DATE=$(date +"%Y%m%d_%H%M%S")
DB_NAME="tvr_website_db"
DB_USER="tvr_admin"
export PGPASSWORD="123456"

mkdir -p $BACKUP_DIR

# Chạy lệnh pg_dump
pg_dump -U $DB_USER -h localhost -F c $DB_NAME > $BACKUP_DIR/db_backup_$DATE.dump

# Tự động xóa các file backup cũ hơn 7 ngày để tiết kiệm dung lượng
find $BACKUP_DIR -type f -name "*.dump" -mtime +7 -exec rm {} \;