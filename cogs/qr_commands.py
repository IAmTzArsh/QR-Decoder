import os
import io
import asyncio
import datetime
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
import qrcode
from qreader import QReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from typing import Optional, List, Union
import numpy as np # Import numpy for qreader compatibility

# Define QR code dimensions and watermark path
QR_DIMENSION = 512  # Fixed dimensions for consistency and readability
WATERMARK_PATH = "assets/watermark.png" # Make sure this path is correct relative to your project root

class QRCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.qreader = QReader() # Initialize QReader once

        # Ensure assets directory exists for watermark
        os.makedirs("assets", exist_ok=True)
        if not os.path.exists(WATERMARK_PATH):
            print(f"Warning: Watermark file not found at {WATERMARK_PATH}. Generated QR codes will not have a watermark.")
            # Optionally, create a dummy watermark or inform the user how to add one.

    def _add_watermark_sync(self, qr_image: Image.Image) -> Image.Image:
        """
        Adds a watermark to the center of the QR code image (synchronous).
        The watermark is scaled to fit without obstructing the QR code significantly.
        """
        if not os.path.exists(WATERMARK_PATH):
            return qr_image # Skip watermarking if file not found

        try:
            watermark = Image.open(WATERMARK_PATH).convert("RGBA")
        except Exception as e:
            print(f"Error loading watermark image: {e}")
            return qr_image

        qr_width, qr_height = qr_image.size
        wm_width, wm_height = watermark.size

        # Determine target watermark size (e.g., 20-30% of QR code size, centered)
        target_wm_width = int(qr_width * 0.25) # 25% of QR width
        target_wm_height = int(qr_height * 0.25) # 25% of QR height

        # Resize watermark while maintaining aspect ratio
        if wm_width > wm_height:
            scale_factor = target_wm_width / wm_width
        else:
            scale_factor = target_wm_height / wm_height

        new_wm_width = int(wm_width * scale_factor)
        new_wm_height = int(wm_height * scale_factor)

        # Ensure watermark is not too big if it was originally very small
        if new_wm_width == 0 or new_wm_height == 0:
            new_wm_width = int(qr_width * 0.1)
            new_wm_height = int(qr_height * 0.1)

        watermark = watermark.resize((new_wm_width, new_wm_height), Image.LANCZOS)

        # Calculate position to center the watermark
        x_offset = (qr_width - new_wm_width) // 2
        y_offset = (qr_height - new_wm_height) // 2

        # Create a transparent layer for the watermark
        temp_img = Image.new('RGBA', qr_image.size, (0, 0, 0, 0))
        temp_img.paste(watermark, (x_offset, y_offset), watermark)

        # Blend the watermark with the QR code
        return Image.alpha_composite(qr_image.convert("RGBA"), temp_img)


    @app_commands.command(name="make", description="Create a QR code from any content.")
    @app_commands.describe(
        content="The text, link, or data to encode in the QR code.",
        style_qr="Hex color code for QR code modules (e.g., #RRGGBB).",
        bg_qr="Hex color code for QR code background (e.g., #RRGGBB).",
        file_attachment="Attach a file to generate a QR code for its content/link.",
        include_timestamp="Whether to include a generation timestamp in the QR content (boolean)."
    )
    async def make_qr(
        self,
        interaction: discord.Interaction,
        content: Optional[str] = None,
        file_attachment: Optional[discord.Attachment] = None,
        style_qr: Optional[str] = None,
        bg_qr: Optional[str] = None,
        include_timestamp: Optional[bool] = False
    ):
        """
        Generates a QR code from provided text, link, or file attachment.
        Supports custom colors, background, watermarking, and timestamping.
        """
        await interaction.response.defer(thinking=True, ephemeral=False) # Defer publicly

        qr_data = content
        if file_attachment:
            # Prefer content from attachment if provided, otherwise fallback to 'content' string
            if file_attachment.content_type and file_attachment.content_type.startswith(('image/', 'video/', 'audio/', 'application/pdf', 'text/')):
                # For common readable files, we might download and read content
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(file_attachment.url) as resp:
                            if resp.status == 200:
                                if file_attachment.size < 1024 * 1024 * 5: # Limit file size to 5MB for reading directly
                                    file_content = await resp.text()
                                    qr_data = file_content # Use file content if readable
                                else:
                                    qr_data = file_attachment.url # Use URL for larger files (silently)
                            else:
                                qr_data = file_attachment.url # Fallback to URL if download fails (silently)
                except Exception as e:
                    qr_data = file_attachment.url # Fallback to URL on any error (silently)
            else:
                qr_data = file_attachment.url # For other types, just use the URL (silently)

        if not qr_data:
            return await interaction.followup.send("Please provide some `content` or attach a `file` to create a QR code.", ephemeral=True)

        # Add timestamp if requested
        if include_timestamp:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            qr_data = f"Generated: {timestamp}\nData: {qr_data}"

        try:
            # Validate and convert hex colors
            fill_color = "#000000" # Default black
            back_color = "#FFFFFF" # Default white

            if style_qr:
                if len(style_qr) == 7 and style_qr.startswith("#"):
                    fill_color = style_qr
                else:
                    await interaction.followup.send("Invalid `style_qr` hex code format. Using default black.", ephemeral=True)

            if bg_qr:
                if len(bg_qr) == 7 and bg_qr.startswith("#"):
                    back_color = bg_qr
                else:
                    await interaction.followup.send("Invalid `bg_qr` hex code format. Using default white.", ephemeral=True)

            # Generate QR code using the qrcode library
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L, # Low error correction
                box_size=10, # Determines the size of each "box" (pixel) in the QR code
                border=4, # Border thickness
            )
            qr.add_data(qr_data)
            qr.make(fit=True)

            # Create PIL image
            pil_img = qr.make_image(fill_color=fill_color, back_color=back_color).convert("RGB")
            pil_img = pil_img.resize((QR_DIMENSION, QR_DIMENSION), Image.LANCZOS) # Ensure fixed dimension

            # Offload watermarking to a thread (using the synchronous version)
            final_img = await asyncio.to_thread(self._add_watermark_sync, pil_img)

            # Save the image to a bytes buffer
            with io.BytesIO() as image_buffer:
                final_img.save(image_buffer, format='PNG')
                image_buffer.seek(0)
                discord_file = discord.File(image_buffer, filename="qrcode.png")

            await interaction.followup.send(
                f"Here's your generated QR code! (Content size: {len(qr_data)} characters)",
                file=discord_file
            )

        except qrcode.exceptions.DataOverflowError:
            await interaction.followup.send("The provided data is too large to fit in a QR code. Please provide shorter content.", ephemeral=True)
        except Exception as e:
            print(f"Error generating QR code: {e}")
            await interaction.followup.send(f"An unexpected error occurred while generating the QR code: `{e}`", ephemeral=True)

    def _process_qr_image_sync(self, image_bytes: bytes, filename: str) -> List[str]:
        """
        Internal function to process an image and read QR codes (synchronous).
        Offloaded to a thread to prevent blocking the event loop.
        Returns a list of decoded strings.
        """
        try:
            image_stream = io.BytesIO(image_bytes)
            # Use Pillow to open the image, allowing support for various formats
            pil_img = Image.open(image_stream).convert("L") # Convert to grayscale for QReader

            # Convert PIL Image to NumPy array, as qreader often prefers this
            np_image = np.array(pil_img)

            decoded_data = self.qreader.detect_and_decode(image=np_image)

            # Filter out None values and ensure unique results if multiple detections yield same data
            return list(set(filter(None, decoded_data)))
        except Exception as e:
            print(f"Error processing QR image '{filename}': {e}")
            raise

    def _generate_qr_pdf_sync(self, qr_contents: List[str], username: str) -> io.BytesIO:
        """
        Generates a styled PDF containing the decoded QR code information (synchronous).
        Offloaded to a thread.
        """
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        title_font_size = 24
        header_font_size = 14
        content_font_size = 10
        padding = 50
        line_height = 20

        # Title
        c.setFont("Helvetica-Bold", title_font_size)
        c.setFillColor(HexColor("#336699")) # A nice blue color
        c.drawString(padding, height - padding, "QR Code Decoding Report")

        # Metadata
        c.setFont("Helvetica", header_font_size)
        c.setFillColor(HexColor("#666666"))
        c.drawString(padding, height - padding - 40, f"Generated for: {username}")
        c.drawString(padding, height - padding - 60, f"Report Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")

        y_position = height - padding - 100

        if not qr_contents:
            c.setFont("Helvetica-Bold", header_font_size)
            c.setFillColor(HexColor("#FF0000"))
            c.drawString(padding, y_position, "No QR codes found or decoded in the provided image(s).")
        else:
            for i, content in enumerate(qr_contents):
                if y_position < padding + 50: # Check if new page is needed
                    c.showPage()
                    y_position = height - padding
                    c.setFont("Helvetica-Bold", header_font_size)
                    c.setFillColor(HexColor("#336699"))
                    c.drawString(padding, y_position, "QR Code Decoding Report (Continued)")
                    y_position -= line_height * 2

                c.setFont("Helvetica-Bold", header_font_size)
                c.setFillColor(HexColor("#000000"))
                c.drawString(padding, y_position, f"QR Code #{i + 1}:")
                y_position -= line_height

                c.setFont("Helvetica", content_font_size)
                c.setFillColor(HexColor("#333333"))

                # Split content into lines for better rendering if too long
                max_chars_per_line = 100
                lines = []
                current_line = ""
                # Handle potential non-string content (though unlikely with qreader output)
                content_str = str(content)
                for word in content_str.split():
                    if len(current_line) + len(word) + 1 > max_chars_per_line:
                        lines.append(current_line)
                        current_line = word
                    else:
                        current_line += (" " if current_line else "") + word
                if current_line:
                    lines.append(current_line)

                # Add a "Decoded Data" label
                c.setFont("Helvetica-Bold", content_font_size)
                c.drawString(padding + 10, y_position, "Decoded Data:")
                y_position -= line_height
                c.setFont("Helvetica", content_font_size)

                # Draw content lines
                for line in lines:
                    c.drawString(padding + 20, y_position, line)
                    y_position -= line_height
                y_position -= line_height # Extra space between QR code entries

        c.save()
        buffer.seek(0)
        return buffer

    @app_commands.command(name="read", description="Decode QR codes from an image or attachment.")
    @app_commands.describe(
        image_attachment="Attach an image containing one or more QR codes."
    )
    async def read_qr(
        self,
        interaction: discord.Interaction,
        image_attachment: discord.Attachment
    ):
        """
        Decodes QR codes from an attached image, supports multiple QR codes.
        Sends a styled PDF report to the user's DMs.
        """
        # Defer ephemerally for privacy.
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not image_attachment.content_type or not image_attachment.content_type.startswith('image/'):
            return await interaction.followup.send("Please attach an image file.", ephemeral=True)

        if image_attachment.size > 1024 * 1024 * 10:
            return await interaction.followup.send("The attached image is too large. Please upload an image smaller than 10MB.", ephemeral=True)

        decoded_qr_data: List[str] = [] # Initialize here to ensure it's always defined
        pdf_buffer: Optional[io.BytesIO] = None # Initialize as None, will hold the PDF data

        try:
            # Download the image asynchronously
            async with aiohttp.ClientSession() as session:
                async with session.get(image_attachment.url) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send(
                            f"Failed to download image from Discord (HTTP status {resp.status}). Please try again.",
                            ephemeral=True
                        )
                    image_bytes = await resp.read()

            # Offload image processing and QR decoding to a separate thread
            decoded_qr_data = await asyncio.to_thread(
                self._process_qr_image_sync, image_bytes, image_attachment.filename
            )

            if not decoded_qr_data:
                await interaction.followup.send("No QR codes found or decoded in the provided image.", ephemeral=True)
                return

            # Offload PDF generation to a separate thread
            pdf_buffer = await asyncio.to_thread(
                self._generate_qr_pdf_sync, decoded_qr_data, interaction.user.display_name
            )

            dm_succeeded = False
            try:
                dm_channel = await interaction.user.create_dm()
                # Ensure the buffer is reset to the beginning before creating the Discord File
                pdf_buffer.seek(0)
                pdf_file = discord.File(pdf_buffer, filename="qr_report.pdf")
                await dm_channel.send(
                    f"Here is your QR code decoding report from `{interaction.guild.name if interaction.guild else 'a private channel'}`:",
                    file=pdf_file
                )
                dm_succeeded = True
            except discord.Forbidden:
                await interaction.followup.send(
                    "I couldn't send the report to your DMs. Please check your privacy settings and allow DMs from server members.",
                    ephemeral=True
                )
            except Exception as e:
                # Log the specific error for debugging
                print(f"Error sending DM to {interaction.user.id} ({interaction.user.name}): {e}")
                # Provide a generic user message for transient errors
                await interaction.followup.send(
                    f"An error occurred while trying to send the report to your DMs: `{e}`. Please try again or check my permissions.",
                    ephemeral=True
                )
            finally:
                # Always send a success message if the DM was sent successfully
                # This ensures the user knows the report was sent, even if a subsequent network hiccup caused an error
                if dm_succeeded:
                    await interaction.followup.send(
                        "Your QR code decoding report has been sent to your DMs for privacy.",
                        ephemeral=True
                    )


        except aiohttp.ClientError as e:
            await interaction.followup.send(f"Network error while fetching the image: `{e}`. Please try again.", ephemeral=True)
        except Exception as e:
            # Catch all other unexpected errors during the main processing
            print(f"Error in read_qr command: {e}")
            await interaction.followup.send(f"An unexpected error occurred while reading the QR code: `{e}`. Please try again.", ephemeral=True)

        finally:
            # Ensure the BytesIO buffer is closed if it was created, to release memory
            if pdf_buffer:
                pdf_buffer.close()


async def setup(bot: commands.Bot):
    """
    Called by discord.py when loading the cog.
    Adds the cog to the bot.
    """
    await bot.add_cog(QRCommands(bot))