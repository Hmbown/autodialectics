import { existsSync } from "node:fs"
import { join } from "node:path"

export const AutodialecticsPlugin = async ({ client, directory }) => {
  const configPath = join(directory, "autodialectics.yaml")
  const hasConfig = existsSync(configPath)

  return {
    "shell.env": async (_input, output) => {
      output.env.AUTODIALECTICS_REPO_ROOT = directory
      if (hasConfig && !output.env.AUTODIALECTICS_CONFIG) {
        output.env.AUTODIALECTICS_CONFIG = configPath
      }
    },

    event: async ({ event }) => {
      if (event.type === "session.created") {
        await client.app.log({
          body: {
            service: "autodialectics-plugin",
            level: "info",
            message: "Autodialectics OpenCode plugin active",
            extra: {
              configPath: hasConfig ? configPath : null
            }
          }
        })
      }
    }
  }
}
