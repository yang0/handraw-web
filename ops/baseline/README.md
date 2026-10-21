# Existing production customizations

Reviewed reference copies of the pre-existing web launcher, Sidekiq launcher, and CDN initializer. Deployment does not overwrite their live counterparts. The launchers assume the existing `yang0` service account rather than assigning its home directory.

The exact original files, Nginx configuration, Supervisor configuration, tracked diffs and untracked assets are retained in the private server baseline backup. Credentials, certificates and runtime secrets are not copied into Git.

Existing static aliases remain owned by the separate static distribution checkout. The portal uses `/studio`, avoiding the original `/handraw` static alias.
