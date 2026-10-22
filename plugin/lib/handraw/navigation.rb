# frozen_string_literal: true

module Handraw
  module Navigation
    def self.render(active: nil, surface: "portal")
      page = File.read(Handraw::Engine.root.join("public", "navigation.html"))
      page = page.sub('data-surface="portal"', "data-surface=\"#{surface}\"")
      page =
        page.sub(
          "data-site-section=\"#{active}\"",
          "data-site-section=\"#{active}\" aria-current=\"page\""
        ) if active
      page
    end

    def self.stylesheet(nonce: nil)
      revision_path = Handraw::Engine.root.join("REVISION")
      revision =
        revision_path.file? ? File.read(revision_path).strip : "development"
      url =
        (
          if revision == "development"
            "/studio/assets/navigation.css"
          else
            "https://static.handraw-style.com/handraw-web/releases/#{revision}/assets/navigation.css"
          end
        )
      base = url.delete_suffix('navigation.css')
      "<link rel=\"stylesheet\" href=\"#{url}\"><link rel=\"stylesheet\" href=\"#{base}market.css\">" +
        %w[image-loader.js market.js forum-experience.js].map { |name| "<script nonce=\"#{nonce}\" src=\"#{base}#{name}\" defer></script>" }.join
    end
  end
end
