# syntax=docker/dockerfile:1.7
FROM postgres:16-alpine

ARG SUPERCRONIC_VERSION=v0.2.33
ARG SUPERCRONIC_SHA1=71b0d58cc53f6bd72cf2f293e09e294b79c666d8

SHELL ["/bin/ash", "-o", "pipefail", "-c"]

# Bake the scheduler into the image instead of downloading executable code on
# every container start. The checksum is pinned to the upstream amd64 release
# used by the university VM deployment.
RUN wget -qO /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && echo "${SUPERCRONIC_SHA1}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod 0555 /usr/local/bin/supercronic

COPY scripts/backup-cycle.sh /scripts/backup-cycle.sh
COPY scripts/verify_latest_backup.sh /scripts/verify_latest_backup.sh
COPY scripts/crontab-backup /scripts/crontab-backup

RUN chmod 0555 /scripts/backup-cycle.sh /scripts/verify_latest_backup.sh \
    && chmod 0444 /scripts/crontab-backup

CMD ["/usr/local/bin/supercronic", "-passthrough-logs", "/scripts/crontab-backup"]