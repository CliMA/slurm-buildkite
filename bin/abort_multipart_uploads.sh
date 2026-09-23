#!/bin/bash
# Abort all in-progress multipart uploads in the R2 artifact bucket.
#
# Interrupted `aws s3 cp` uploads (e.g. a cancelled upload_artifacts_r2.jl run)
# leave dangling multipart uploads that occupy storage until aborted. This lists
# and aborts every one of them.
#
# Requires AWS CLI v2 on PATH and R2 credentials in AWS_ACCESS_KEY_ID /
# AWS_SECRET_ACCESS_KEY.
set -euo pipefail

BUCKET="clima-artifacts"
ENDPOINT="https://ec0773bbe656bc4aa705c4ab6d4bf190.r2.cloudflarestorage.com"

aws s3api list-multipart-uploads \
  --bucket "$BUCKET" \
  --endpoint-url "$ENDPOINT" \
  --query 'Uploads[].[Key,UploadId]' \
  --output text | while read -r KEY UPLOAD_ID; do
    [ -z "$KEY" ] && continue
    echo "Aborting: $KEY ($UPLOAD_ID)"
    aws s3api abort-multipart-upload \
      --bucket "$BUCKET" \
      --key "$KEY" \
      --upload-id "$UPLOAD_ID" \
      --endpoint-url "$ENDPOINT"
done
