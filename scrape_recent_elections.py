# -*- coding: utf-8 -*-

from models import *
from requests import session
from bs4 import BeautifulSoup
from time import sleep
import os
import io
import re
import inspect

# select the race_types into a list of matching purposes
race_types = []

for race_type in Race_Type.select():
	race_types.append(race_type)

url = 'http://enrarchives.sos.mo.gov/enrnet/Default.aspx'

name_pattern = re.compile("^(?P<first>[\w'\.]+) (?:(?P<middle>[\w\.]+) )?(?:\((?P<nickname>.+)\) )?(?P<last>[\w\- '\.]+)(?:, (?P<suffix>Jr\.|Sr\.|[IV]+))?$")

elections = []

# set up a requests session
with session() as r_sesh:

	# set session headers
	r_sesh.headers.update({ 
		  'Accept-Language': 'en-US,en;q=0.8'
		, 'Cache-Control': 'no-cache'
		, 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
		, 'Host': 'enrarchives.sos.mo.gov'
		, 'Origin': 'http://enrarchives.sos.mo.gov'
		, 'Referer': 'http://enrarchives.sos.mo.gov/enrnet/Default.aspx'
		, 'X-MicrosoftAjax': 'Delta=true'
		, 'X-Requested-With': 'XMLHttpRequest'
		, 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36'
	})

	# request the first page
	response = r_sesh.get(url)

	soup = BeautifulSoup(response.content, 'lxml')

	# grab the VIEWSTATE variable
	view_state = soup.select("#__VIEWSTATE")[0]['value']

	# for each option in the elections dropdown...
	for opt in soup.find('select', id = 'MainContent_cboElectionNames').find_all('option'):
		
		spl_txt = opt.text.split(' - ')

		# set up a new election
		election = Election(
				  election_date = spl_txt[-1].strip()
				, opt_value = opt['value']
				, races = []
			)

		# check each election type...
		for elec_type in Election_Type.select():
			if elec_type.name in spl_txt[0]:
				# then set this attribute
				election.election_type = elec_type

		# append to the global list of elections
		elections.append(election)

	# go back over each collected election
	for election in elections:

		# pause between requests
		sleep(3)

		# make a requeest with the election dropdown value
		response = r_sesh.post(
			  url
			, data = {
				  'ctl00$sm1': 'ctl00$MainContent$UpdatePanel1|ctl00$MainContent$btnElectionType'
				, '__EVENTTARGET': ''
				, '__EVENTARGUMENT': ''
				, 'ctl00$MainContent$cboElectionNames': election.opt_value
				, '__ASYNCPOST': 'true'
				, 'ctl00$MainContent$btnElectionType': 'Submit'
				, '__VIEWSTATE': view_state
			}
		)

		# parse results
		soup = BeautifulSoup(response.content, 'lxml')

		# loop over the rows in the electtable...
		for tr in soup.find('table', class_ = 'electtable').find_all('tr')[1:]:

			tds = tr.find_all('td')

			# if there's a <strong> tag in the first column...
			if tds[0].find('strong') != None:

				# set up a new race
				race = Race(
					  candidates = []
					, total_votes = None
					, num_precincts = re.search('\d+', tds[3].text).group()
				)

				# set which type of race it is
				for race_type in race_types:
					if race_type.name in tds[0].text:
						# then set this attribute
						race.race_type = race_type.id

				# try matching to a district number and setting this race attribute
				try:
					race.district = re.search('\d+', tds[0].text.split(' - ')[1]).group()
				except (IndexError, AttributeError):
					pass
				except Exception as e:
					print type(e)
					print e

			# if the second, third and fourth columns have text...
			elif len(tds[1].text.strip())>0 and len(tds[2].text.strip())>0 and len(tds[3].text.strip())>0:

				# append a new candidate to the race's candidate list
				race.candidates.append(Race_Candidate(
					  raw_name = tds[0].text.strip()
					, party = tds[1].text.strip()
					, votes = tds[2].text.strip().replace(',', '')
					, pct_votes = tds[3].text.replace('%', '').strip()
				))

			# if the second column contains the phrase 'Total Votes'...
			elif tds[1].text.strip() == 'Total Votes:':

				# set the race's total votes
				race.total_votes = tds[2].text.replace(',', '').strip()
				# then append the race to the election
				election.races.append(race)

			else:
				pass

# go back over all the elections
for election in elections:

	# save the election
	try:
		with db.atomic():
			election.save()
	except Exception as e:
		if 'duplicate' in e.message:
			pass
		else:
			print 'Error on line #{0}: {1}'.format(inspect.currentframe().f_lineno, e)

	for race in election.races:

		# ignore races with types we don't recognize
		if race.race_type_id != None:
			# for now, only focus on the state legislative races
			if 'State Senator' in race.race_type.name or 'State Representatives' in race.race_type.name:

				race.election = election.id

				# save the race
				try:
					with db.atomic():
						race.save()
				except Exception as e:
					if 'duplicate' in e.message:
						pass
					else:
						print 'Error on line #{0}: {1}'.format(inspect.currentframe().f_lineno, e)

				# now loop over the candidates
				for candidate in race.candidates:

					candidate.race = race.id

					print candidate.raw_name

					# add suffix to pattern
					# split match and pattern

					name_dict = re.match(name_pattern, candidate.raw_name).groupdict()
				
					candidate.first_name = name_dict['first']
					candidate.middle_name = name_dict['middle']
					candidate.last_name = name_dict['last']
					candidate.nickname = name_dict['nickname']
					candidate.name_suffix = name_dict['suffix']

				try:
					with db.atomic():
						candidate.save()
				except Exception as e:
					if 'duplicate' in e.message:
						pass
					else:
						print 'Error on line #{0}: {1}'.format(inspect.currentframe().f_lineno, e)

print 'fin.'

