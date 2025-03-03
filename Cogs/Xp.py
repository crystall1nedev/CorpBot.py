import asyncio, discord, datetime, time, random
from   discord.ext import commands
from   Cogs import Settings, DisplayName, Nullify, CheckRoles, Message, PickList

def setup(bot):
	# Add the bot and deps
	settings = bot.get_cog("Settings")
	bot.add_cog(Xp(bot, settings))

# This is the xp module.  It's likely to be retarded.

class Xp(commands.Cog):

	# Init with the bot reference, and a reference to the settings var
	def __init__(self, bot, settings):
		self.bot = bot
		self.settings = settings
		self.is_current = False # Used for stopping loops
		self.loop_time = 600 # Default is 10 minutes (600 seconds)
		global Utils, DisplayName
		Utils = self.bot.get_cog("Utils")
		DisplayName = self.bot.get_cog("DisplayName")

	async def _can_xp(self, user, server, requiredXP = None, promoArray = None):
		# Checks whether or not said user has access to the xp system
		if requiredXP is None:
			requiredXP = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"RequiredXPRole",None)
		if promoArray is None:
			promoArray = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"PromotionArray",[])

		if not requiredXP:
			return True

		for checkRole in user.roles:
			if str(checkRole.id) == str(requiredXP):
				return True
				
		# Still check if we have enough xp
		userXP = self.settings.getUserStat(user, server, "XP")
		for role in promoArray:
			if str(role["ID"]) == str(requiredXP):
				if userXP >= role["XP"]:
					return True
				break
		return False

	# Proof of concept stuff for reloading cog/extension
	def _is_submodule(self, parent, child):
		return parent == child or child.startswith(parent + ".")

	@commands.Cog.listener()
	async def on_unloaded_extension(self, ext):
		# Called to shut things down
		if not self._is_submodule(ext.__name__, self.__module__):
			return
		self.is_current = False

	@commands.Cog.listener()
	async def on_loaded_extension(self, ext):
		# See if we were loaded
		if not self._is_submodule(ext.__name__, self.__module__):
			return
		self.is_current = True
		self.bot.loop.create_task(self.addXP())
		
	async def addXP(self):
		print("Starting XP loop: {}".format(datetime.datetime.now().time().isoformat()))
		await self.bot.wait_until_ready()
		last_loop = 0
		while not self.bot.is_closed():
			try:
				# Gather our wait time by taking the (last_loop - self.loop_time)
				wait_time = max(self.loop_time-last_loop,0) # Fall back on 0 if something goes awry
				print("Last XP/Role Check loop took {} seconds - waiting for {} seconds...".format(last_loop,wait_time))
				await asyncio.sleep(wait_time)
				if not self.is_current:
					# Bail if we're not the current instance
					return
				# Get the start time
				t = time.time()
				updates = await self.update_xp()
				for update in updates:
					await CheckRoles.checkroles(update["user"], update["chan"], self.settings, self.bot, **update["kwargs"])
				# Retain how long the update took
				last_loop = time.time()-t
			except Exception as e:
				last_loop = 0 # Reset the loop time
				print(str(e))

	async def update_xp(self):
		responses = []
		t = time.time()
		print("Adding XP: {}".format(datetime.datetime.now().time().isoformat()))
		# Get some values that don't require immediate query
		server_dict = {}
		for x in self.bot.get_all_members():
			memlist = server_dict.get(str(x.guild.id), [])
			memlist.append(x)
			server_dict[str(x.guild.id)] = memlist
		for server_id in server_dict:
			server = self.bot.get_guild(int(server_id))
			if not server:
				continue

			# The getServerStat() calls are run *a lot* - same with getUserStat(), so we prevent them from
			# blocking by running them in the bot loop's executor
			xpAmount     = int(await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"HourlyXP"))
			xpAmount     = float(xpAmount/6)
			xpRAmount    = int(await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"HourlyXPReal"))
			xpRAmount    = float(xpRAmount/6)

			# Make sure we have something to add
			if not xpAmount and not xpRAmount:
				continue

			xpLimit      = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"XPLimit")
			xprLimit     = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"XPReserveLimit")

			# Cast as int if not None
			if xpLimit is not None:
				xpLimit = int(xpLimit)
			if xprLimit is not None:
				xprLimit = int(xprLimit)

			# See if we have a limit that prevents adding
			if xpLimit==0 and xprLimit==0:
				continue

			onlyOnline   = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"RequireOnline")
			requiredXP   = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"RequiredXPRole")
			promoArray   = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"PromotionArray")

			xpblock      = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"XpBlockArray")
			targetChanID = await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"DefaultChannel")

			kwargs = {
				"xp_promote":await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"XPPromote"),
				"xp_demote":await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"XPDemote"),
				"suppress_promotions":await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"SuppressPromotions"),
				"suppress_demotions":await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"SuppressDemotions"),
				"only_one_role":await self.bot.loop.run_in_executor(None,self.settings.getServerStat,server,"OnlyOneRole")
			}
			for user in server_dict[server_id]:

				# First see if we're current - we want to bail quickly
				if not self.is_current:
					print("XP Interrupted, no longer current - took {} seconds.".format(time.time() - t))
					return responses
				
				if not await self._can_xp(user,server,requiredXP,promoArray):
					continue

				bumpXP = False
				if onlyOnline == False:
					bumpXP = True
				else:
					if user.status == discord.Status.online:
						bumpXP = True

				# Check if we're blocked
				if user.id in xpblock:
					# No xp for you
					continue

				for role in user.roles:
					if role.id in xpblock:
						bumpXP = False
						break
						
				if bumpXP:
					if xpAmount > 0:
						# User is online add hourly xp reserve
						
						# First we check if we'll hit our limit
						skip = False
						if not xprLimit is None:
							# Get the current values
							newxp = await self.bot.loop.run_in_executor(None,self.settings.getUserStat,user,server,"XPReserve")
							# Make sure it's this xpr boost that's pushing us over
							# This would only push us up to the max, but not remove
							# any we've already gotten
							if newxp + xpAmount > xprLimit:
								skip = True
								if newxp < xprLimit:
									await self.bot.loop.run_in_executor(None,self.settings.setUserStat,user,server,"XPReserve",xprLimit)
						if not skip:
							xpLeftover = await self.bot.loop.run_in_executor(None,self.settings.getUserStat,user,server,"XPLeftover")

							if xpLeftover is None:
								xpLeftover = 0
							else:
								xpLeftover = float(xpLeftover)
							gainedXp = xpLeftover+xpAmount
							gainedXpInt = int(gainedXp) # Strips the decimal point off
							xpLeftover = float(gainedXp-gainedXpInt) # Gets the < 1 value
							await self.bot.loop.run_in_executor(None,self.settings.setUserStat,user,server,"XPLeftover",xpLeftover)
							await self.bot.loop.run_in_executor(None,self.settings.incrementStat,user,server,"XPReserve",gainedXpInt)
					
					if xpRAmount > 0:
						# User is online add hourly xp

						# First we check if we'll hit our limit
						skip = False
						if not xpLimit is None:
							# Get the current values
							newxp = await self.bot.loop.run_in_executor(None,self.settings.getUserStat,user,server,"XP")
							# Make sure it's this xpr boost that's pushing us over
							# This would only push us up to the max, but not remove
							# any we've already gotten
							if newxp + xpRAmount > xpLimit:
								skip = True
								if newxp < xpLimit:
									await self.bot.loop.run_in_executor(None,self.settings.setUserStat,user,server,"XP")
						if not skip:
							xpRLeftover = await self.bot.loop.run_in_executor(None,self.settings.getUserStat,user,server,"XPRealLeftover")
							if xpRLeftover is None:
								xpRLeftover = 0
							else:
								xpRLeftover = float(xpRLeftover)
							gainedXpR = xpRLeftover+xpRAmount
							gainedXpRInt = int(gainedXpR) # Strips the decimal point off
							xpRLeftover = float(gainedXpR-gainedXpRInt) # Gets the < 1 value
							await self.bot.loop.run_in_executor(None,self.settings.setUserStat,user,server,"XPRealLeftover",xpRLeftover)
							await self.bot.loop.run_in_executor(None,self.settings.incrementStat,user,server,"XP",gainedXpRInt)

						# Check our default channels
						targetChan = None
						if len(str(targetChanID)):
							# We *should* have a channel
							tChan = self.bot.get_channel(int(targetChanID))
							if tChan:
								# We *do* have one
								targetChan = tChan
						responses.append({"user":user, "chan":targetChan if targetChan else self.bot.get_guild(int(server_id)), "kwargs":kwargs})
		print("XP Done - took {} seconds.".format(time.time() - t))
		return responses

	@commands.command()
	async def xp(self, ctx, *, member = None, xpAmount : int = None):
		"""Gift xp to other members."""

		author  = ctx.message.author
		server  = ctx.guild
		channel = ctx.message.channel

		if not ctx.guild:
			# Can only run in a server
			return await ctx.send("This command cannot be run in dm.")

		usage = 'Usage: `{}xp [role/member] [amount]`'.format(ctx.prefix)

		isRole = False

		if member is None:
			await ctx.send(usage)
			return

		# Check for formatting issues
		if xpAmount is None:
			# Either xp wasn't set - or it's the last section
			if type(member) is str:
				# It' a string - the hope continues
				roleCheck = DisplayName.checkRoleForInt(member, server)
				if not roleCheck:
					# Returned nothing - means there isn't even an int
					msg = 'I couldn\'t find *{}* on the server.'.format(Nullify.escape_all(member))
					await ctx.send(msg)
					return
				if roleCheck["Role"]:
					isRole = True
					member   = roleCheck["Role"]
					xpAmount = roleCheck["Int"]
				else:
					# Role is invalid - check for member instead
					nameCheck = DisplayName.checkNameForInt(member, server)
					if not nameCheck:
						await ctx.send(usage)
						return
					if not nameCheck["Member"]:
						msg = 'I couldn\'t find *{}* on the server.'.format(Nullify.escape_all(member))
						await ctx.send(msg)
						return
					member   = nameCheck["Member"]
					xpAmount = nameCheck["Int"]

		if xpAmount is None:
			# Still no xp - let's run stats instead
			if isRole:
				await ctx.send(usage)
			else:
				await ctx.invoke(self.stats, member=member)
			return
		if not type(xpAmount) is int:
			await ctx.send(usage)
			return

		# Get our user/server stats
		isAdmin         = Utils.is_admin(ctx)
		checkAdmin = self.settings.getServerStat(ctx.guild, "AdminArray")
		# Check for bot admin
		isBotAdmin      = Utils.is_bot_admin_only(ctx)

		botAdminAsAdmin = self.settings.getServerStat(server, "BotAdminAsAdmin")
		adminUnlim      = self.settings.getServerStat(server, "AdminUnlimited")
		reserveXP       = self.settings.getUserStat(author, server, "XPReserve")
		requiredXP      = self.settings.getServerStat(server, "RequiredXPRole")
		xpblock         = self.settings.getServerStat(server, "XpBlockArray")

		approve = True
		decrement = True
		admin_override = False

		# RequiredXPRole
		if not await self._can_xp(author, server):
			approve = False
			msg = 'You don\'t have the permissions to give xp.'

		if xpAmount > int(reserveXP):
			approve = False
			msg = 'You can\'t give *{:,} xp*, you only have *{:,}!*'.format(xpAmount, reserveXP)

		if author == member:
			approve = False
			msg = 'You can\'t give yourself xp!  *Nice try...*'

		if xpAmount < 0:
			msg = 'Only admins can take away xp!'
			approve = False
			# Avoid admins gaining xp
			decrement = False

		if xpAmount == 0:
			msg = 'Wow, very generous of you...'
			approve = False

		# Check bot admin
		if isBotAdmin and botAdminAsAdmin:
			# Approve as admin
			approve = True
			admin_override = True
			if adminUnlim:
				# No limit
				decrement = False
			else:
				if xpAmount < 0:
					# Don't decrement if negative
					decrement = False
				if xpAmount > int(reserveXP):
					# Don't approve if we don't have enough
					msg = 'You can\'t give *{:,} xp*, you only have *{:,}!*'.format(xpAmount, reserveXP)
					approve = False
			
		# Check admin last - so it overrides anything else
		if isAdmin:
			# No limit - approve
			approve = True
			admin_override = True
			if adminUnlim:
				# No limit
				decrement = False
			else:
				if xpAmount < 0:
					# Don't decrement if negative
					decrement = False
				if xpAmount > int(reserveXP):
					# Don't approve if we don't have enough
					msg = 'You can\'t give *{:,} xp*, you only have *{:,}!*'.format(xpAmount, reserveXP)
					approve = False

		# Check author and target for blocks
		# overrides admin because admins set this.
		if type(member) is discord.Role:
			if member.id in xpblock:
				msg = "That role cannot receive xp!"
				approve = False
		else:
			# User
			if member.id in xpblock:
				msg = "That member cannot receive xp!"
				approve = False
			else:
				for role in member.roles:
					if role.id in xpblock:
						msg = "That member's role cannot receive xp!"
						approve = False
		
		if ctx.author.id in xpblock:
			msg = "You can't give xp!"
			approve = False
		else:
			for role in ctx.author.roles:
				if role.id in xpblock:
					msg = "Your role cannot give xp!"
					approve = False

		if approve:

			self.bot.dispatch("xp", member, ctx.author, xpAmount)

			if isRole:
				# XP was approved - let's iterate through the users of that role,
				# starting with the lowest xp
				#
				# Work through our members
				memberList = []
				sMemberList = self.settings.getServerStat(server, "Members")
				for amem in server.members:
					if amem == author:
						continue
					if amem.id in xpblock:
						# Blocked - only if not admin sending it
						continue
					roles = amem.roles
					if member in roles:
						# This member has our role
						# Add to our list
						for smem in sMemberList:
							# Find our server entry
							if str(smem) == str(amem.id):
								# Add it.
								sMemberList[smem]["ID"] = smem
								memberList.append(sMemberList[smem])
				memSorted = sorted(memberList, key=lambda x:int(x['XP']))
				if len(memSorted):
					# There actually ARE members in said role
					totalXP = xpAmount
					# Gather presets
					xp_p = self.settings.getServerStat(server,"XPPromote")
					xp_d = self.settings.getServerStat(server,"XPDemote")
					xp_sp = self.settings.getServerStat(server,"SuppressPromotions")
					xp_sd = self.settings.getServerStat(server,"SuppressDemotions")
					xp_oo = self.settings.getServerStat(server,"OnlyOneRole")
					if xpAmount > len(memSorted):
						# More xp than members
						leftover = xpAmount % len(memSorted)
						eachXP = (xpAmount-leftover)/len(memSorted)
						for i in range(0, len(memSorted)):
							# Make sure we have anything to give
							if leftover <= 0 and eachXP <= 0:
								break
							# Carry on with our xp distribution
							cMember = DisplayName.memberForID(memSorted[i]['ID'], server)
							if leftover>0:
								self.settings.incrementStat(cMember, server, "XP", eachXP+1)
								leftover -= 1
							else:
								self.settings.incrementStat(cMember, server, "XP", eachXP)
							await CheckRoles.checkroles(
								cMember,
								channel,
								self.settings,
								self.bot,
								xp_promote=xp_p,
								xp_demote=xp_d,
								suppress_promotions=xp_sp,
								suppress_demotions=xp_sd,
								only_one_role=xp_oo)
					else:
						for i in range(0, xpAmount):
							cMember = DisplayName.memberForID(memSorted[i]['ID'], server)
							self.settings.incrementStat(cMember, server, "XP", 1)
							await CheckRoles.checkroles(
								cMember,
								channel,
								self.settings,
								self.bot,
								xp_promote=xp_p,
								xp_demote=xp_d,
								suppress_promotions=xp_sp,
								suppress_demotions=xp_sd,
								only_one_role=xp_oo)

					# Decrement if needed
					if decrement:
						self.settings.incrementStat(author, server, "XPReserve", (-1*xpAmount))
					msg = '*{:,} collective xp* was given to *{}!*'.format(totalXP, Nullify.escape_all(member.name))
					await channel.send(msg)
				else:
					msg = 'There are no eligible members in *{}!*'.format(Nullify.escape_all(member.name))
					await channel.send(msg)

			else:
				# Decrement if needed
				if decrement:
					self.settings.incrementStat(author, server, "XPReserve", (-1*xpAmount))
				# XP was approved!  Let's say it - and check decrement from gifter's xp reserve
				msg = '*{}* was given *{:,} xp!*'.format(DisplayName.name(member), xpAmount)
				await channel.send(msg)
				self.settings.incrementStat(member, server, "XP", xpAmount)
				# Now we check for promotions
				await CheckRoles.checkroles(member, channel, self.settings, self.bot)
		else:
			await channel.send(msg)
			
	'''@xp.error
	async def xp_error(self, ctx, error):
		msg = 'xp Error: {}'.format(error)
		await ctx.channel.send(msg)'''

	@commands.command()
	async def defaultrole(self, ctx):
		"""Lists the default role that new users are assigned."""

		role = self.settings.getServerStat(ctx.guild, "DefaultRole")
		if role is None or role == "":
			msg = 'New users are not assigned a role on joining this server.'
			await ctx.channel.send(msg)
		else:
			# Role is set - let's get its name
			found = False
			for arole in ctx.guild.roles:
				if str(arole.id) == str(role):
					found = True
					msg = 'New users will be assigned to **{}**.'.format(Nullify.escape_all(arole.name))
			if not found:
				msg = 'There is no role that matches id: `{}` - consider updating this setting.'.format(role)
			await ctx.send(msg)
		
	@commands.command()
	async def gamble(self, ctx, bet = None):
		"""Gamble your xp reserves for a chance at winning xp!"""
		
		author  = ctx.message.author
		server  = ctx.guild
		channel = ctx.message.channel
		
		# bet must be a multiple of 10, member must have enough xpreserve to bet
		msg = 'Usage: `{}gamble [xp reserve bet] (must be multiple of 10)`'.format(ctx.prefix)

		try:
			bet = int(float(bet))
		except:
			return await ctx.send(msg)

		isAdmin    = Utils.is_admin(ctx)
		checkAdmin = self.settings.getServerStat(ctx.guild, "AdminArray")
		# Check for bot admin
		isBotAdmin = Utils.is_bot_admin_only(ctx)
		botAdminAsAdmin = self.settings.getServerStat(server, "BotAdminAsAdmin")
		adminUnlim = self.settings.getServerStat(server, "AdminUnlimited")
		reserveXP  = self.settings.getUserStat(author, server, "XPReserve")
		minRole    = self.settings.getServerStat(server, "MinimumXPRole")
		requiredXP = self.settings.getServerStat(server, "RequiredXPRole")
		xpblock    = self.settings.getServerStat(server, "XpBlockArray")

		approve = True
		decrement = True

		# Check Bet
			
		if not bet % 10 == 0:
			approve = False
			msg = 'Bets must be in multiples of *10!*'
			
		if bet > int(reserveXP):
			approve = False
			msg = 'You can\'t bet *{:,}*, you only have *{:,}* xp reserve!'.format(bet, reserveXP)
			
		if bet < 0:
			msg = 'You can\'t bet negative amounts!'
			approve = False
			
		if bet == 0:
			msg = 'You can\'t bet *nothing!*'
			approve = False

		# RequiredXPRole
		if not await self._can_xp(author, server):
			approve = False
			msg = 'You don\'t have the permissions to gamble.'
				
		# Check bot admin
		if isBotAdmin and botAdminAsAdmin:
			# Approve as admin
			approve = True
			if adminUnlim:
				# No limit
				decrement = False
			else:
				if bet < 0:
					# Don't decrement if negative
					decrement = False
				if bet > int(reserveXP):
					# Don't approve if we don't have enough
					msg = 'You can\'t bet *{:,}*, you only have *{:,}* xp reserve!'.format(bet, reserveXP)
					approve = False
			
		# Check admin last - so it overrides anything else
		if isAdmin:
			# No limit - approve
			approve = True
			if adminUnlim:
				# No limit
				decrement = False
			else:
				if bet < 0:
					# Don't decrement if negative
					decrement = False
				if bet > int(reserveXP):
					# Don't approve if we don't have enough
					msg = 'You can\'t bet *{:,}*, you only have *{:,}* xp reserve!'.format(bet, reserveXP)
					approve = False

		# Check if we're blocked
		if ctx.author.id in xpblock:
			msg = "You can't gamble for xp!"
			approve = False
		else:
			for role in ctx.author.roles:
				if role.id in xpblock:
					msg = "Your role cannot gamble for xp!"
					approve = False
			
		if approve:
			# Bet was approved - let's take the XPReserve right away
			if decrement:
				takeReserve = -1*bet
				self.settings.incrementStat(author, server, "XPReserve", takeReserve)
			
			# Bet more, less chance of winning, but more winnings!
			if bet < 100:
				betChance = 5
				payout = int(bet/10)
			elif bet < 500:
				betChance = 15
				payout = int(bet/4)
			else:
				betChance = 25
				payout = int(bet/2)
			
			# 1/betChance that user will win - and payout is 1/10th of the bet
			randnum = random.randint(1, betChance)
			# print('{} : {}'.format(randnum, betChance))
			if randnum == 1:
				# YOU WON!!
				self.settings.incrementStat(author, server, "XP", int(payout))
				msg = '*{}* bet *{:,}* and ***WON*** *{:,} xp!*'.format(DisplayName.name(author), bet, int(payout))
				# Now we check for promotions
				await CheckRoles.checkroles(author, channel, self.settings, self.bot)
			else:
				msg = '*{}* bet *{:,}* and.... *didn\'t* win.  Better luck next time!'.format(DisplayName.name(author), bet)
			
		await ctx.send(msg)
			
	@commands.command()
	async def recheckroles(self, ctx):
		"""Re-iterate through all members and assign the proper roles based on their xp (admin only)."""

		author  = ctx.message.author
		server  = ctx.guild
		channel = ctx.message.channel

		isAdmin = Utils.is_admin(ctx)

		# Only allow admins to change server stats
		if not isAdmin:
			await channel.send('You do not have sufficient privileges to access this command.')
			return
		
		# Gather presets
		xp_p = self.settings.getServerStat(server,"XPPromote")
		xp_d = self.settings.getServerStat(server,"XPDemote")
		xp_sp = self.settings.getServerStat(server,"SuppressPromotions")
		xp_sd = self.settings.getServerStat(server,"SuppressDemotions")
		xp_oo = self.settings.getServerStat(server,"OnlyOneRole")
		message = await ctx.channel.send('Checking roles...')

		changeCount = 0
		for member in server.members:
			# Now we check for promotions
			if await CheckRoles.checkroles(
								member,
								channel,
								self.settings,
								self.bot,
								True,
								xp_promote=xp_p,
								xp_demote=xp_d,
								suppress_promotions=xp_sp,
								suppress_demotions=xp_sd,
								only_one_role=xp_oo):
				changeCount += 1
		
		if changeCount == 1:
			await message.edit(content='Done checking roles.\n\n*1 user* updated.')
			#await channel.send('Done checking roles.\n\n*1 user* updated.')
		else:
			await message.edit(content='Done checking roles.\n\n*{:,} users* updated.'.format(changeCount))
			#await channel.send('Done checking roles.\n\n*{} users* updated.'.format(changeCount))

	@commands.command()
	async def recheckrole(self, ctx, *, user : discord.Member = None):
		"""Re-iterate through all members and assign the proper roles based on their xp (admin only)."""

		author  = ctx.message.author
		server  = ctx.guild
		channel = ctx.message.channel

		isAdmin = Utils.is_admin(ctx)

		# Only allow admins to change server stats
		if not isAdmin:
			await channel.send('You do not have sufficient privileges to access this command.')
			return

		if not user:
			user = author

		# Now we check for promotions
		if await CheckRoles.checkroles(user, channel, self.settings, self.bot):
			await channel.send('Done checking roles.\n\n*{}* was updated.'.format(DisplayName.name(user)))
		else:
			await channel.send('Done checking roles.\n\n*{}* was not updated.'.format(DisplayName.name(user)))



	@commands.command()
	async def listxproles(self, ctx):
		"""Lists all roles, id's, and xp requirements for the xp promotion/demotion system."""
		# Get the array
		promoArray = self.settings.getServerStat(ctx.guild, "PromotionArray", [])

		# Sort by XP first, then by name
		promoSorted = sorted(promoArray, key=lambda x:int(x['XP']), reverse=True)
		
		if not len(promoSorted):
			desc = None
		else:
			title = "Current XP Roles ({:,} total)".format(len(promoSorted))
			desc = ""
			for arole in promoSorted:
				# Get current role name based on id
				foundRole = False
				for role in ctx.guild.roles:
					if str(role.id) == str(arole['ID']):
						# We found it
						foundRole = True
						desc += '{} : *{:,} XP*\n'.format(role.mention,arole['XP'])
				if not foundRole:
					desc += '**{}** ({}) : *{:,} XP* (removed from server)\n'.format(Nullify.escape_all(arole['Name']),arole["ID"],arole['XP'])

		# Get the required role for using the xp system
		role = self.settings.getServerStat(ctx.guild, "RequiredXPRole")
		required = ""
		if role is None or role == "":
			required = "**Everyone** can give xp, gamble, and feed the bot."
		else:
			# Role is set - let's get its name
			found = False
			for arole in ctx.guild.roles:
				if str(arole.id) == str(role):
					found = True
					required = "You need to be a{} {} to *give xp*, *gamble*, or *feed* the bot.".format(
						"n" if arole.name[:1].lower() in "aeiou" else "",
						arole.mention
					)
					break
			if not found:
				required = "There is no role that matches id: `{}` for using the xp system - consider updating that setting.".format(role)

		if desc is None:
			return await ctx.send(
				"There are no roles in the xp role list.  You can add some with the `{}addxprole [role] [xpamount]` command!\n{}".format(ctx.prefix,required)
			)
		# Update the description and send the message
		desc = "{}\n\n{}".format(required,desc)
		return await PickList.PagePicker(
			title=title,
			description=desc,
			color=ctx.author,
			ctx=ctx
		).pick()		
		
	@commands.command()
	async def rank(self, ctx, *, member = None):
		"""Say the highest rank of a listed member."""

		if member is None:
			member = ctx.message.author
			
		if type(member) is str:
			memberName = member
			member = DisplayName.memberForName(memberName, ctx.guild)
			if not member:
				msg = 'I couldn\'t find *{}*...'.format(Nullify.escape_all(memberName))
				await ctx.send(msg)
				return
			
		# Create blank embed
		stat_embed = discord.Embed(color=member.color)
			
		promoArray = self.settings.getServerStat(ctx.guild, "PromotionArray")
		# promoSorted = sorted(promoArray, key=itemgetter('XP', 'Name'))
		promoSorted = sorted(promoArray, key=lambda x:int(x['XP']))
		
		
		member_name = getattr(member,"global_name",None) or member.name
		# Get member's avatar url
		avURL = Utils.get_avatar(member)
		if getattr(member,"nick",None) and member.nick != member_name:
			# We have a nickname - add to embed
			stat_embed.set_author(name='{}, who currently goes by {}'.format(member_name, member.nick), icon_url=avURL)
		else:
			# Add to embed
			stat_embed.set_author(name='{}'.format(member_name), icon_url=avURL)
			
		
		highestRole = ""
		
		for role in promoSorted:
			# We *can* have this role, let's see if we already do
			currentRole = None
			for aRole in member.roles:
				# Get the role that corresponds to the id
				if str(aRole.id) == str(role['ID']):
					# We found it
					highestRole = aRole.name

		if highestRole == "":
			msg = '*{}* has not acquired a rank yet.'.format(DisplayName.name(member))
			# Add Rank
			stat_embed.add_field(name="Current Rank", value='None acquired yet', inline=True)
		else:
			msg = '*{}* is a **{}**!'.format(DisplayName.name(member), highestRole)
			# Add Rank
			stat_embed.add_field(name="Current Rank", value=highestRole, inline=True)
			
		# await ctx.send(msg)
		await ctx.send(embed=stat_embed)
		
	@rank.error
	async def rank_error(self, error, ctx):
		msg = 'rank Error: {}'.format(error)
		await ctx.channel.send(msg)

	async def _show_xp(self, ctx, reverse=False):
		# Helper to list xp
		message = await Message.EmbedText(title="Counting Xp...",color=ctx.author).send(ctx)
		sorted_array = sorted([(int(await self.bot.loop.run_in_executor(None, self.settings.getUserStat,x,ctx.guild,"XP",0)),x) for x in ctx.guild.members],key=lambda x:(x[0],x[1].id),reverse=reverse)
		# Update the array with the user's place in the list
		xp_array = [{
			"name":"{}. {} ({} {})".format(i,x[1].display_name,x[1],x[1].id),
			"value":"{:,} XP".format(x[0])
			} for i,x in enumerate(sorted_array,start=1)]
		return await PickList.PagePicker(
			title="{} Xp-Holders in {} ({:,} total)".format("Top" if reverse else "Bottom",ctx.guild.name,len(xp_array)),
			list=xp_array,
			color=ctx.author,
			ctx=ctx,
			message=message
		).pick()

	# List the top 10 xp-holders
	@commands.command()
	async def leaderboard(self, ctx):
		"""List the top xp-holders."""
		return await self._show_xp(ctx,reverse=True)
		
	# List the top 10 xp-holders
	@commands.command()
	async def bottomxp(self, ctx):
		"""List the bottom xp-holders."""
		return await self._show_xp(ctx,reverse=False)

	async def _get_member_and_server(self, ctx, value):
		if not isinstance(value,str):
			return (value, ctx.guild)
		# Walk the components split by spaces and see if we can find a member + server
		parts = value.split(" ")
		for i in range(len(parts)+1):
			m = " ".join(parts[:len(parts)-i])
			s = " ".join([] if i==0 else parts[-i:])
			server_test = member_test = None # Initialize
			# Check for a server first
			if s:
				for serv in self.bot.guilds:
					if (serv.name.lower() == s.lower() or str(serv.id) == s):
						# Make sure the author is in that server
						if Utils.is_owner(ctx,ctx.author) or serv.get_member(ctx.author.id):
							# We got a valid server, and are in it
							server_test = serv
							break
				# Didn't find one - don't allow trailing nonsense
				if not server_test:
					continue
				# Got a server - let's see if we have a member to check - or default
				# to the command author
				if not m:
					member_test = server_test.get_member(ctx.author.id)
			# Check if we got a member
			if m:
				# Check if we have a server (either detected or ctx.guild)
				if server_test or ctx.guild:
					member_test = DisplayName.memberForName(m,server_test or ctx.guild)
				else:
					# No server at all - try to get a user
					try: member_test = await self.bot.fetch_user(int(m))
					except: pass
			# Only bail if we have a member
			if member_test:
				return (member_test, server_test or ctx.guild)
		return (None,None)

	@commands.command(aliases=["statsxp","xps","sxp"])
	async def xpstats(self, ctx, *, member=None):
		"""List only the xp and xp reserve of the passed member."""

		member = member or ctx.author
		m,s = await self._get_member_and_server(ctx,member)
		if m is None or s is None:
			return await ctx.send("I couldn't find {}...".format(
				Nullify.escape_all(member or "that member")
			))
		# Gather our XP and XP Reserve here
		url = Utils.get_avatar(m)
		# Create blank embed
		stat_embed = Message.Embed(color=m.color,thumbnail=url,pm_after_fields=20)
		m_name = getattr(m,"global_name",None) or m.name
		if getattr(m,"nick",None) and m.nick != m_name:
			# We have a nickname
			stat_embed.author = '{}, who currently goes by {}'.format(m_name, m.nick)
		else:
			# Add to embed
			stat_embed.author = m_name
		# Get user's xp
		newStat = int(self.settings.getUserStat(m, s, "XP"))
		newState = int(self.settings.getUserStat(m, s, "XPReserve"))
		# Add XP and XP Reserve
		stat_embed.add_field(name="XP", value="{:,}".format(newStat), inline=True)
		stat_embed.add_field(name="XP Reserve", value="{:,}".format(newState), inline=True)
		# Add server info if outside the command context
		if s != ctx.guild:
			stat_embed.add_field(name="Server Name", value=s.name, inline=True)
			stat_embed.add_field(name="Server ID", value=s.id, inline=True)
		await stat_embed.send(ctx)
		
	# List the xp and xp reserve of a user
	@commands.command()
	async def stats(self, ctx, *, member=None):
		"""List a number of stats about the passed member."""
		
		m,server = await self._get_member_and_server(ctx,member or ctx.author)
		if m: member = m
		if isinstance(member,str) and not server:
			# Try to resolve the member name to a user as-is
			m = DisplayName.memberForName(member,server)
			if m: member = m

		if not member or isinstance(member,str):
			return await ctx.send("I couldn't find {}...".format(
				Nullify.escape_all(member or "that member")
			))

		url = Utils.get_avatar(member)

		# Create blank embed
		stat_embed = Message.Embed(color=member.color,thumbnail=url,pm_after_fields=20)

		# Get Created timestamp
		created = "Unknown"
		if getattr(member,"created_at",None) != None:
			ts = int(member.created_at.timestamp())
			created = "<t:{0}> (<t:{0}:R>)".format(ts)
		stat_embed.description = "Created {}".format(created)

		member_name = getattr(member,"global_name",None) or member.name
		if getattr(member,"nick",None) and member.nick != member_name:
			# We have a nickname
			stat_embed.author = '{}, who currently goes by {}'.format(member_name, member.nick)
		else:
			# Add to embed
			stat_embed.author = member_name

		if server:
			# Get user's xp
			newStat = int(self.settings.getUserStat(member, server, "XP"))
			newState = int(self.settings.getUserStat(member, server, "XPReserve"))
			
			# Add XP and XP Reserve
			stat_embed.add_field(name="XP", value="{:,}".format(newStat), inline=True)
			stat_embed.add_field(name="XP Reserve", value="{:,}".format(newState), inline=True)

			# Get user's current role
			promoArray = self.settings.getServerStat(server, "PromotionArray")
			# promoSorted = sorted(promoArray, key=itemgetter('XP', 'Name'))
			promoSorted = sorted(promoArray, key=lambda x:int(x['XP']))
			
			highestRole = None
			if len(promoSorted):
				nextRole = promoSorted[0]
			else:
				nextRole = None

			for role in promoSorted:
				if int(nextRole['XP']) < newStat:
					nextRole = role
				# We *can* have this role, let's see if we already do
				currentRole = None
				for aRole in member.roles:
					# Get the role that corresponds to the id
					if str(aRole.id) == str(role['ID']):
						# We found it
						highestRole = aRole.name
						if len(promoSorted) > (promoSorted.index(role)+1):
							# There's more roles above this
							nRoleIndex = promoSorted.index(role)+1
							nextRole = promoSorted[nRoleIndex]

			if highestRole:
				# Add Rank
				stat_embed.add_field(name="Current Rank", value=highestRole, inline=True)
			elif len(promoSorted):
				# Need to have ranks to acquire one
				stat_embed.add_field(name="Current Rank", value='None acquired yet', inline=True)
			
			if nextRole and (newStat < int(nextRole['XP'])):
				# Get role
				next_role = DisplayName.roleForID(int(nextRole["ID"]), server)
				if not next_role:
					next_role_text = "Role ID: {} (Removed from server)".format(nextRole["ID"])
				else:
					next_role_text = next_role.name
				# Add Next Rank
				stat_embed.add_field(name="Next Rank", value='{} ({:,} more xp required)'.format(next_role_text, int(nextRole['XP'])-newStat), inline=True)
			
			# Get Joined timestamp
			joined = join_pos = "Unknown"
			if getattr(member,"joined_at",None):
				ts = int(member.joined_at.timestamp())
				joined = "<t:{0}> (<t:{0}:R>)".format(ts)
				joinedList = sorted([{"ID":mem.id,"Joined":mem.joined_at} for mem in getattr(server,"members",[])], key=lambda x:x["Joined"].timestamp() if x["Joined"] != None else -1)
				try:
					check_item = { "ID" : member.id, "Joined" : member.joined_at }
					total = len(joinedList)
					position = joinedList.index(check_item) + 1
					join_pos = "{:,} of {:,}".format(position, total)
				except:
					pass
			stat_embed.add_field(name="Joined", value=joined, inline=False)
			stat_embed.add_field(name="Join Position", value=join_pos, inline=server!=ctx.guild)

			# Add server info if outside the command context
			if server != ctx.guild:
				stat_embed.add_field(name="Server Name", value=server.name, inline=True)
				stat_embed.add_field(name="Server ID", value=server.id, inline=True)

			if getattr(member,"premium_since",None) != None:
				ts = int(member.premium_since.timestamp())
				boosted = "<t:{0}> (<t:{0}:R>)".format(ts)
				stat_embed.add_field(name="Boosting Since",value=boosted,inline=False)

		# Get User Name (and ID if not migrated)
		if getattr(getattr(member,"_user",None),"is_migrated",False):
			user_name = member.name
		else:
			user_name = str(member)
		stat_embed.add_field(name="User Name", value=user_name, inline=True)
		stat_embed.add_field(name="User ID", value=str(member.id), inline=True)
		# Add status
		if getattr(member,"status",None):
			status_text = {
				discord.Status.offline: ":black_heart: Offline",
				discord.Status.dnd: ":heart: Do Not Disturb",
				discord.Status.idle: ":yellow_heart: Idle",
			}.get(member.status,":green_heart: Online")
			stat_embed.add_field(name="Status", value=status_text, inline=True)
		
		if getattr(member,"activities",None):
			for activity in member.activities:
				if not activity.name: continue
				# Performing some activity!
				play_dict = {
					discord.ActivityType.playing:"Playing",
					discord.ActivityType.streaming:"Streaming",
					discord.ActivityType.listening:"Listening to",
					discord.ActivityType.watching:"Watching",
					discord.ActivityType.custom:"Custom Status",
					discord.ActivityType.competing:"Competing in"
				}
				play_string = play_dict.get(activity.type,"Playing")
				play_value  = str(activity.name)
				if isinstance(activity,discord.Spotify):
					# Got a Spotify track - let's customize the info
					artist_list = ", ".join([x for x in (", ".join(activity.artists[:-2]),", and ".join(activity.artists[-2:])) if x])
					play_value = "[{}]({}) by {} on Spotify".format(
						activity.title,
						activity.track_url,
						artist_list
					)
				elif isinstance(activity,discord.CustomActivity):
					# Try to extract the relevant info
					play_value = activity.state
					emoji      = activity.emoji
					if not play_value or play_value == "Custom Status":
						# This is the default for no text
						play_value = None
					if activity.emoji:
						# Try to retrieve the emoji, fall back on a question mark
						emoji_check = self.bot.get_emoji(activity.emoji.id)
						emoji = str(emoji_check) if emoji_check else "`:{}:`".format(activity.emoji.name)
					play_value = " ".join([x for x in (emoji,play_value) if x])
					if not play_value:
						# Nothing to display - continue
						continue
				activity_start = getattr(activity,"start",None)
				if activity_start:
					# Strip " to" and " in" from the name
					suffix = ""
					if play_string.endswith((" to"," in")):
						suffix = play_string[-3:]
						play_string = play_string[:-3]
					# Format the name to [Status] - Started [timestamp]
					play_string = "Started {} <t:{}:R>{}".format(
						play_string,
						int(activity_start.timestamp()),
						suffix
					)
				if activity.type == discord.ActivityType.streaming:
					# Prepend the URL
					play_string = "[Watch Now]({}) - {}".format(activity.url,play_string)
				stat_embed.add_field(name=play_string, value=play_value, inline=False)

		# Check if server owner
		if server and server.owner.id == member.id:
			stat_embed.add_field(name="Server Owner", value="👑", inline=True)
		if Utils.is_owner(ctx,member):
			stat_embed.add_field(name="Bot Owner", value="🤖", inline=True)

		await stat_embed.send(ctx)
		
	@stats.error
	async def stats_error(self, ctx, error):
		msg = 'stats Error: {}'.format(error)
		await ctx.channel.send(msg)


	# List the xp and xp reserve of a user
	@commands.command()
	async def xpinfo(self, ctx):
		"""Gives a quick rundown of the xp system."""

		server  = ctx.guild
		channel = ctx.message.channel

		serverName = Nullify.escape_all(server.name)
		hourlyXP = int(self.settings.getServerStat(server, "HourlyXP"))
		hourlyXPReal = int(self.settings.getServerStat(server, "HourlyXPReal"))
		xpPerMessage = int(self.settings.getServerStat(server, "XPPerMessage"))
		xpRPerMessage = int(self.settings.getServerStat(server, "XPRPerMessage"))
		if not xpPerMessage:
			xpPerMessage = 0
		if not xpRPerMessage:
			xpRPerMessage = 0
		if not hourlyXPReal:
			hourlyXPReal = 0
		if not hourlyXP:
			hourlyXP = 0
		onlyOnline = self.settings.getServerStat(server, "RequireOnline")
		xpProm = self.settings.getServerStat(server, "XPPromote")
		xpDem = self.settings.getServerStat(server, "XPDemote")
		xpStr = None

		if xpProm and xpDem:
			# Bot promote and demote
			xpStr = "This is what I check to handle promotions and demotions.\n"
		else:
			if xpProm:
				xpStr = "This is what I check to handle promotions.\n"
			elif xpDem:
				xpStr = "This is what I check to handle demotions.\n"

		msg = "__***{}'s*** **XP System**__\n\n__What's What:__\n\n".format(serverName)
		msg = "{}**XP:** This is the xp you have *earned.*\nIt comes from other users gifting you xp, or if you're lucky enough to `{}gamble` and win.\n".format(msg, ctx.prefix)
		
		if xpStr:
			msg = "{}{}".format(msg, xpStr)
		
		hourStr = None
		if hourlyXPReal > 0:
			hourStr = "Currently, you receive *{} xp* each hour".format(hourlyXPReal)
			if onlyOnline:
				hourStr = "{} (but *only* if your status is *Online*).".format(hourStr)
			else:
				hourStr = "{}.".format(hourStr)
		if hourStr:
			msg = "{}{}\n".format(msg, hourStr)
			
		if xpPerMessage > 0:
			msg = "{}Currently, you receive *{} xp* per message.\n".format(msg, xpPerMessage)
			
		msg = "{}This can only be taken away by an *admin*.\n\n".format(msg)
		msg = "{}**XP Reserve:** This is the xp you can *gift*, *gamble*, or use to *feed* me.\n".format(msg)

		hourStr = None
		if hourlyXP > 0:
			hourStr = "Currently, you receive *{} xp reserve* each hour".format(hourlyXP)
			if onlyOnline:
				hourStr = "{} (but *only* if your status is *Online*).".format(hourStr)
			else:
				hourStr = "{}.".format(hourStr)
		
		if hourStr:
			msg = "{}{}\n".format(msg, hourStr)
		
		if xpRPerMessage > 0:
			msg = "{}Currently, you receive *{} xp reserve* per message.\n".format(msg, xpRPerMessage)

		msg = "{}\n__How Do I Use It?:__\n\nYou can gift other users xp by using the `{}xp [user] [amount]` command.\n".format(msg, ctx.prefix)
		msg = "{}This pulls from your *xp reserve*, and adds to their *xp*.\n".format(msg)
		msg = "{}It does not change the *xp* you have *earned*.\n\n".format(msg)

		msg = "{}You can gamble your *xp reserve* to have a chance to win a percentage back as *xp* for yourself.\n".format(msg)
		msg = "{}You do so by using the `{}gamble [amount in multiple of 10]` command.\n".format(msg, ctx.prefix)
		msg = "{}This pulls from your *xp reserve* - and if you win, adds to your *xp*.\n\n".format(msg)

		msg = "{}You can also *feed* me.\n".format(msg)
		msg = "{}This is done with the `{}feed [amount]` command.\n".format(msg, ctx.prefix)
		msg = "{}This pulls from your *xp reserve* - and doesn't affect your *xp*.\n\n".format(msg)
		
		msg = "{}You can check your *xp*, *xp reserve*, current role, and next role using the `{}stats` command.\n".format(msg, ctx.prefix)
		msg = "{}You can check another user's stats with the `{}stats [user]` command.\n\n".format(msg, ctx.prefix)

		# Get the required role for using the xp system
		role = self.settings.getServerStat(server, "RequiredXPRole")
		if role is None or role == "":
			msg = '{}Currently, **Everyone** can *give xp*, *gamble*, and *feed* the bot.\n\n'.format(msg)
		else:
			# Role is set - let's get its name
			found = False
			for arole in server.roles:
				if str(arole.id) == str(role):
					found = True
					vowels = "aeiou"
					if arole.name[:1].lower() in vowels:
						msg = '{}Currently, you need to be an **{}** to *give xp*, *gamble*, or *feed* the bot.\n\n'.format(msg, Nullify.escape_all(arole.name))
					else:
						msg = '{}Currently, you need to be a **{}** to *give xp*, *gamble*, or *feed* the bot.\n\n'.format(msg, Nullify.escape_all(arole.name))
			if not found:
				msg = '{}There is no role that matches id: `{}` for using the xp system - consider updating that setting.\n\n'.format(msg, role)

		msg = "{}Hopefully that clears things up!".format(msg)

		await ctx.send(msg)
