# frozen_string_literal: true

require "rails_helper"

RSpec.describe Handraw::BundleStore do
  describe ".validate!" do
    it "accepts a portable bilingual resource manifest" do
      Tempfile.create(["handraw", ".zip"]) do |file|
        Zip::OutputStream.open(file.path) do |archive|
          archive.put_next_entry("manifest.json")
          archive.write(JSON.generate(schema_version: 1, resource: {
            kind: "layout", license: "允许个人与商业创作。", prompt_zh: "左右对照布局。", prompt_en: "Two-column comparison.",
          }))
        end
        expect(described_class.validate!(file.path, "layout").dig("resource", "kind")).to eq("layout")
      end
    end

    it "rejects path traversal even when the manifest otherwise looks valid" do
      Tempfile.create(["handraw", ".zip"]) do |file|
        Zip::OutputStream.open(file.path) do |archive|
          archive.put_next_entry("../outside.txt")
          archive.write("unsafe")
        end
        expect { described_class.validate!(file.path, "style") }.to raise_error(Handraw::RuleError, /不安全路径/)
      end
    end
  end
end
