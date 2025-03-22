import discord
from discord import app_commands
from discord.ext import commands
import requests
from bs4 import BeautifulSoup

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Função para obter a URL do avatar do Roblox usando web scraping
def get_roblox_avatar_url(username):
    try:
        # Acessa a página do perfil do usuário
        url = f"https://www.roblox.com/users/profile?username={username}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)

        # Verifica se a requisição foi bem-sucedida
        if response.status_code != 200:
            print(f"Erro ao acessar o perfil: {response.status_code}")
            return None

        # Faz o parsing do HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Encontra a tag da imagem do avatar
        avatar_tag = soup.find("img", {"class": "avatar-image"})
        if avatar_tag:
            return avatar_tag["src"]
        else:
            print("Tag da imagem do avatar não encontrada.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição: {e}")
        return None

# Evento quando o bot está pronto
@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')
    try:
        # Sincroniza os Slash Commands
        synced = await bot.tree.sync()
        print(f"Comandos sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Erro ao sincronizar comandos: {e}")

# Slash Command para obter o avatar do Roblox
@bot.tree.command(name="avatar", description="Obtenha a imagem do avatar de um usuário do Roblox")
@app_commands.describe(username="Nome de usuário do Roblox")
async def avatar(interaction: discord.Interaction, username: str):
    await interaction.response.defer()  # Adia a resposta para evitar timeout
    avatar_url = get_roblox_avatar_url(username)
    if avatar_url:
        await interaction.followup.send(f"Avatar de **{username}**: {avatar_url}")
    else:
        await interaction.followup.send(f"Não foi possível encontrar o usuário **{username}** ou obter o avatar. Verifique o nome de usuário e tente novamente.")

# Inicia o bot
bot.run('MTM1MjgwMDA4OTIwMjIyOTM1OQ.GFDvHE.BLQLvgdh3EM9k4_vH3fSokSaiuEwtKgDCtnrqk')  # Substitua pelo seu token