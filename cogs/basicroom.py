from database.room import *
from discord.ext import commands
import discord

class BasicRoom(commands.Cog, name=get_text('_cog')['room']):
    def __init__(self, bot):
        self.bot = bot
        self.color = discord.Color.blurple()
        # TODO: invitee list to db
        # self.invitee_list = db.get_table('invitees', primary_id='id')
        self.invitee_list = []

    @commands.command()
    async def new(self, ctx, *args):
        if not ctx.guild.me.guild_permissions.manage_channels or not ctx.guild.me.guild_permissions.manage_roles:
            raise discord.ext.commands.errors.CommandInvokeError("Missing Permissons")
   
        settings = Settings.get_for(ctx.guild.id)
        player = ctx.message.author

        # check if able to make room
        if settings.allow_multiple_rooms and Room.get_hosted(player.id, ctx.guild.id):
            return await ctx.send(settings.get_text('already_is_host'))
        elif not settings.allow_multiple_rooms and Room.player_is_in_any(player.id, ctx.guild.id):
            return await ctx.send(settings.get_text('already_in_room'))

        # activity (room name)
        if len(args) < 1 and player.activity and player.activity and player.activity.name and len(player.activity.name) > 1:
            activity = player.activity.name
        elif args:
            activity = remove_mentions(" ".join(args))
        else:
            activity = choice(settings.default_names).format(player.display_name)
        activity = activity[0:90].strip()
        # color
        if player.top_role.color != discord.Color.default():
            color = player.top_role.color
        else:
            color = discord.Color(int(choice(settings.default_colors)))

        # role
        role = await ctx.guild.create_role(
            name="({}) {}".format(settings.get_text('room'), activity),
            color=color,
            hoist=True,
            mentionable=True )

        # overwrites
        accessors_ids = settings.access_all_rooms_role
        accessors = []
        for accessor_id in accessors_ids:
            accessor_player = ctx.guild.get_member(accessor_id)
            accessor_role = ctx.guild.get_role(accessor_id)
            if accessor_player:
                accessors.append(accessor_player)
            elif accessor_role:
                accessors.append(accessor_role)
        if len(accessors) < 1:
            accessors = list(filter(lambda m : m.bot, ctx.guild.members))

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True),
            role: discord.PermissionOverwrite(read_messages=True)
        }
        for accessor in accessors:
            overwrites[accessor] = discord.PermissionOverwrite(read_messages=True)

        # channel
        category = await get_rooms_category(ctx.guild)
        channel = await ctx.guild.create_text_channel(
            name=activity,
            category=category,
            position=0,
            overwrites=overwrites
        )

        voice_channel = None
        if settings.default_voice_channel:
            voice_channel = await ctx.guild.create_voice_channel(
                name=activity,
                bitrate=settings.bitrate * 1000,
                category=category,
                position=0,
                overwrites=overwrites
            )

        # new room
        room = Room(
            role_id=role.id,
            channel_id=channel.id,
            voice_channel_id=voice_channel.id if voice_channel else 0,
            guild=ctx.guild.id,
            birth_channel=ctx.message.channel.id,
            host=player.id,
            players=[player.id],
            activity=activity,
            color=color,
            lock=settings.default_lock,
            description=choice(settings.default_descriptions),
            size=settings.default_size,
            timeout=settings.default_timeout,
            created=now(),
            last_active=now()
        )
        await player.add_roles(role)
        await channel.edit(topic="({}/{}) {}".format(len(room.players), room.size, room.description))
        await channel.send(choice(settings.join_messages).format(player.display_name))
        embed = room.get_embed(player, settings.get_text('new_room'))
        message = await ctx.send(embed=embed)
        await message.add_reaction('➡️')


    @commands.command()
    async def join(self, ctx, *args):
        settings = Settings.get_for(ctx.guild.id)
        if len(args) < 1:
            return await ctx.send(settings.get_text('missing_target_room'))
        room = Room.get_by_any(ctx, args)
        if room:
            (success, response) = await self.try_join(ctx, room, ctx.author)
            if success:
                message = await ctx.send(embed=response)
                if not room.lock:
                    await message.add_reaction('➡️')
            else:
                await ctx.send(response)
        else:
            await ctx.send(settings.get_text('room_not_exist'))


    @commands.command()
    async def invite(self, ctx, *args):
        settings = Settings.get_for(ctx.guild.id)
        if len(args) < 1:
            return await ctx.send(settings.get_text('missing_target'))
        user_mentions = ctx.message.mentions
        role_mentions = ctx.message.role_mentions
        player = ctx.message.author
        invitees = []
        room = None
        
        for invitee in user_mentions:
            if invitee.id not in invitees:
                invitees.append(invitee.id)

        for role in role_mentions:
            for member in role.members:
                if member.id not in invitees:
                    invitees.append(member.id)

        player_names = []
        for member in ctx.guild.members:
            player_names.append(member.display_name.lower())
            player_names.append(member.name.lower())

        for arg in args:
            if arg in player_names:
                p = discord.utils.find(lambda p: p.name.lower() == arg.lower(), ctx.guild.members)
                if p and p.id not in invitees:
                    invitees.append(p.id)

        rooms = rooms_db.find(guild=ctx.guild.id)
        room_match = None
        if rooms:
            for room_data in rooms:
                r = Room.from_query(room_data)
                if player.id in r.players:
                    room = r
        if not room:
            return await ctx.send(settings.get_text('not_in_room'))

        if not invitees:
            return await ctx.send(settings.get_text('missing_target_invitees'))
                    
        room.update_active()
        embed = discord.Embed(
            color=discord.Color.blurple(),
            timestamp=now(),
            title=choice(settings.get_text('invite_messages')).format(player.display_name, room.activity) )
        embed.add_field(
            name="{} ({}/{})".format(settings.get_text('players'), len(room.players), room.size),
            value="<@{}>".format(">, <@".join([str(id) for id in room.players])) )
        embed.add_field(
            name=settings.get_text('inviter') + ": " + player.display_name,
            value=settings.get_text('server') + ": " + ctx.guild.name )
        embed.add_field(
            name=settings.get_text('room') + ": " + room.activity,
            value=settings.get_text('description') + ": " + room.description )
        embed.add_field(
            name="ID",
            value=room.role_id )
        embed.set_footer(
            text=settings.get_text('invite_instructions'),
            icon_url=discord.Embed.Empty )


        result_embed = discord.Embed(
            color=discord.Color.blurple(),
            description="{}: `{}`".format(settings.get_text('room'), room.activity),
            timestamp=now(),
            title=settings.get_text('invites_sent') )
        result_embed.set_footer(
            text="{}: {}".format(settings.get_text('inviter'), player.display_name),
            icon_url=discord.Embed.Empty )
        invitee_success = []
        invitee_fail = []
        invitee_already_joined = []
        for invitee_id in invitees:
            try:
                if invitee_id in room.players:
                    invitee_already_joined.append(invitee_id)
                    continue
                invitee = self.bot.get_user(invitee_id)
                m = await invitee.send(embed=embed)
                await m.add_reaction('✅')
                await m.add_reaction('❌')
                self.invitee_list.append(invitee_id)
                invitee_success.append(invitee_id)
            except discord.errors.Forbidden as e:
                invitee_fail.append(invitee_id)

        if invitee_success:
            result_embed.add_field(
                name=settings.get_text('invitees'),
                value="<@{}>".format(">, <@".join([str(id) for id in invitee_success])) )
        if invitee_fail:
            result_embed.add_field(
                name=settings.get_text('failed_invites'),
                value="{}\n<@{}>".format(settings.get_text('failed_invites_description'), ">, <@".join([str(id) for id in invitee_fail])) )
        if invitee_already_joined:
            result_embed.add_field(
                name=settings.get_text('already_joined'),
                value="<@{}>".format(">, <@".join([str(id) for id in invitee_already_joined])) )
            
        return await ctx.send(embed=result_embed)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        settings = Settings.get_for(reaction.message.channel.guild.id)
        leave = reaction.emoji == '➡️'
        if leave and reaction.message.author.id == self.bot.user.id and not user.bot:
            for field in reaction.message.embeds[0].fields:
                if field.name == settings.get_text('channel'):
                    channel_id = field.value[2:-1] # remove mention
                    room_data = rooms_db.find_one(channel_id=channel_id)
                    if room_data:
                        room = Room.from_query(room_data)
                        await self.try_leave(reaction.message.channel, room, user)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        settings = Settings.get_for(reaction.message.channel.guild.id)
        join = reaction.emoji == '➡️'
        if join and reaction.message.author.id == self.bot.user.id and not user.bot:
            for field in reaction.message.embeds[0].fields:
                if field.name == settings.get_text('channel'):
                    channel_id = field.value[2:-1] # remove mention
                    room_data = rooms_db.find_one(channel_id=channel_id)
                    if room_data:
                        room = Room.from_query(room_data)
                        await self.try_join(reaction.message.channel, room, user)
            return

        player = user
        channel = reaction.message.channel
        accept = reaction.emoji == '✅'
        decline = reaction.emoji == '❌'
        valid_invite_emoji = accept or decline
        from_dm = type(channel) is discord.channel.DMChannel
        if not valid_invite_emoji or player.id not in self.invitee_list or not from_dm:
            return

        self.invitee_list.remove(player.id)
        room_id = None
        for field in reaction.message.embeds[0].fields:
            if field.name == "ID":
                room_id = field.value
                break
        room = None
        room_data = rooms_db.find_one(role_id=room_id)
        if room_data:
            room = Room.from_query(room_data)
        if not room:
            return await channel.send(settings.get_text('room_not_exist'))

        if (accept):
            guild = self.bot.get_guild(room.guild)
            if not guild:
                return await channel.send(settings.get_text('room_not_exist'))
            await channel.send(settings.get_text('invite_accepted'))
            # TODO:
            (success, response) = await self.try_join(reaction.message.channel, room, user)
            if success:
                await channel.send(embed=response)
            else:
                await channel.send(response)
        else:
            await channel.send(settings.get_text('invite_declined'))
                

    @commands.command()
    async def leave(self, ctx, *args):
        settings = Settings.get_for(ctx.guild.id)
        player = ctx.message.author
        rooms = Room.get_player_rooms(player.id, ctx.guild.id)
        room = None
        if len(rooms) > 1:
            role_mention_filter = ctx.message.role_mentions[0].id if ctx.message.role_mentions else None
            text_filter = ' '.join(args).lower() if args else None
            for r in rooms:
                match_channel = ctx.channel.id == r.channel_id
                match_text = text_filter and text_filter in r.activity.lower()
                match_role = role_mention_filter == r.role_id
                if match_channel or match_text or match_role:
                    room = r
                    break
            if not room:
                return await ctx.send(settings.get_text('in_multiple_rooms'))
            
        elif len(rooms) == 1:
            room = rooms[0]
        else:
            return await ctx.send(settings.get_text('not_in_room'))

        if room:
            (success, response) = await self.try_leave(ctx, room, player)
            if success and response and ctx.channel.id != room.channel_id:
                try:
                    await ctx.send(response)
                except:
                    pass
        else:
            return await ctx.send(settings.get_text('no_room'))


    @commands.command()
    async def ls(self, ctx):
        settings = Settings.get_for(ctx.guild.id)
        rooms = rooms_db.find(guild=ctx.guild.id)
        embed = discord.Embed(color=discord.Color.blurple())
        count = 0

        for room_data in rooms:
            count += 1
            room = Room.from_query(room_data)

            description = room.description if room.description else "{}: {}".format(settings.get_text('players'), ', '.join(room.players))
            embed.add_field(
                name="{}{} ({}/{})".format(":lock: " if room.lock else "", room.activity, len(room.players), room.size),
                value=description,
                inline=False )
        if count > 0:
            embed.title = "{} ({})".format(settings.get_text('rooms'), count)
            await ctx.send(embed=embed)
        else:
            await ctx.send(settings.get_text('no_rooms'))


    @commands.command()
    async def look(self, ctx, *args):
        settings = Settings.get_for(ctx.guild.id)
        r = Room.get_by_any(ctx, args)
        if r:
            message = await ctx.send(embed=r.get_embed(ctx.author, settings.get_text('request'))) 
            if not r.lock:
                await message.add_reaction('➡️')
        else:
            await ctx.send(settings.get_text('no_room'))


    async def try_join(self, ctx, room, player):
        settings = Settings.get_for(ctx.guild.id)
        room.update_active()
        if not settings.allow_multiple_rooms and Room.player_is_in_any(player.id, ctx.guild.id):
            return (False, settings.get_text('already_in_room'))
        if room.lock:
            return (False, settings.get_text('join_locked_room'))
        if room.size <= len(room.players):
            return (False, settings.get_text('join_full_room'))

        if await room.add_player(player):
            embed = room.get_embed(player, settings.get_text('room_joined'))
            room_channel = ctx.guild.get_channel(room.channel_id)
            await room_channel.send(choice(settings.join_messages).format(player.display_name))
            if len(room.players) >= room.size:
                role = ctx.guild.get_role(room.role_id)
                await ctx.send(settings.get_text('full_room_notification').format(role.mention, len(room.players)))
            return (True, embed)
        else:
            return (False, settings.get_text('retry_error'))

    async def try_leave(self, ctx, room, player):
        settings = Settings.get_for(ctx.guild.id)
        room.update_active()
        if room.host == player.id:
            role = ctx.guild.get_role(room.role_id)
            await room.disband(ctx.guild)
            return (True, settings.get_text('disband_room').format(player.display_name, room.activity))
        elif player.id in room.players:
            (success, response) = await room.remove_player(player)
            if success:
                try:
                    room_channel = ctx.guild.get_channel(room.channel_id)
                    await room_channel.send(choice(settings.leave_messages).format(player.display_name))
                    if response:
                        await ctx.send(response)
                except:
                    pass
                return (True, settings.get_text('left_room').format(player.name, room.activity))
            else:
                return (True, settings.get_text('retry_error'))
        return (False, None)



def setup(bot):
    load_cog(bot, BasicRoom(bot))