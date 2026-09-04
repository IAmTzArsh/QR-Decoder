import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Define intents
intents = discord.Intents.all() # As requested, for full functionality and future expansion

class QRBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)
        # Using when_mentioned_or("!") as a fallback, but we'll focus on slash commands.
        self.initial_extensions = ['cogs.qr_commands'] # List of cogs to load

    async def setup_hook(self):
        """Called automatically by discord.py when the bot is ready to start processing commands."""
        print(f"Loading extensions...")
        for extension in self.initial_extensions:
            try:
                await self.load_extension(extension)
                print(f"Loaded {extension}")
            except Exception as e:
                print(f"Failed to load extension {extension}. Error: {e}")

        # Sync application commands (slash commands)
        # For development, you might sync to a specific guild for faster updates:
        # Replace YOUR_GUILD_ID with your actual test server ID.
        # await self.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))
        # print(f"Application commands synced for guild {YOUR_GUILD_ID}!")

        # For production, sync globally (can take up to an hour to propagate)
        await self.tree.sync()
        print("Application commands synced globally!")


    async def on_ready(self):
        """Event fired when the bot has successfully connected to Discord."""
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('Bot is ready!')

if __name__ == "__main__":
    bot = QRBot()
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN not found in .env file.")
        exit(1)
    TOKEN = TOKEN.strip().strip('"').strip("'")
    bot.run(TOKEN)