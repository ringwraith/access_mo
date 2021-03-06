# -*- coding: utf-8 -*-

from models import *
from model_helpers import parse_name, get_or_create_person, get_party, get_or_create_source_doc
from requests import session
from bs4 import BeautifulSoup
from time import sleep
import re
import inspect

# select the race_types into a list of matching purposes
race_types = []

for race_type in Race_Type.select():
	race_types.append(race_type)

url = 'http://enrarchives.sos.mo.gov/enrnet/Default.aspx'

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

	soup = BeautifulSoup(response.content, 'html5lib')

	# grab the VIEWSTATE variable
	view_state = soup.select("#__VIEWSTATE")[0]['value']

	# for each option in the elections dropdown...
	for opt in soup.find('select', id = 'MainContent_cboElectionNames').find_all('option'):

		spl_txt = opt.text.split(' - ')

		# set up a new election
		election = Election(
				  name = opt.text.strip()
				, election_date = spl_txt[-1].strip()
				, opt_value = opt['value']
				, races = []
			)

		# get or create the source doc for the election
		election.source_doc = get_or_create_source_doc(
				  source = 'SoS'
				, name = election.name
				, file_name = 'source_docs/SoS/election_results/html/{}.html'.format(election.name.replace('-', '').replace(',', '').replace(' ', '_').replace('__', '_'))
				, url = 'http://enrarchives.sos.mo.gov/enrnet/Default.aspx?eid={}'.format(election.opt_value)
				, parent = None
			)

		# check each election type...
		for elec_type in Election_Type.select():
			if elec_type.name in spl_txt[0]:
				# then set this attribute
				election.election_type = elec_type

		# if it's a general election...
		if election.election_type.name == 'General':
			# assume it's for the assembly starting next year
			election.assembly = Assembly.get(start_year = int(re.search('\d{4}', election.election_date).group()) + 1)
		# if it's a special election...
		elif election.election_type.name == 'Special':
			try: 
				# first, try getting an assembly that started the same year...
				election.assembly = Assembly.get(start_year = int(re.search('\d{4}', election.election_date).group()))
			except Assembly.DoesNotExist:
				# then try getting an assembly that ended the same year...
				election.assembly = Assembly.get(end_year = int(re.search('\d{4}', election.election_date).group()))

		# append to the global list of elections
		elections.append(election)

	# go back over each collected election
	for election in elections:

		# try opening the local html file
		try:
			with open(election.source_doc.file_name, 'r') as f:
				content = f.read()
		except:
			print '   No file found.'
			print '   Requesting results from {}'.format(election.name)
			
			# if there isn't one, wait, then request it
			sleep(3)
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
			
			content = response.content

			# then save a local copy of the html file
			with open(election.source_doc.file_name, 'w') as f:
				f.write(content)

		# parse response
		soup = BeautifulSoup(content, 'html5lib')

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

				# if "unexpired" appears in the text, set this attribute
				if 'unexpired' in tds[0].text:
					race.unexpired = True
				else:
					race.unexpired = False

			# if the second, third and fourth columns have text...
			elif len(tds[1].text.strip())>0 and len(tds[2].text.strip())>0 and len(tds[3].text.strip())>0:

				# append a new candidate to the race's candidate list
				race.candidates.append(Race_Candidate(
					  raw_name = tds[0].text.replace('  ', ' ').strip()
					, party = get_party(tds[1].text.strip())
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
			
			# for now, ignore judicial races, propositions and constitutional amendments
			if race.race_type.name not in [
				  'Constitutional Amendment'
				, 'Proposition'
				, 'Court of Appeals'
				, 'Missouri Supreme Court'
				, 'Circuit Judge'
				, 'Assoc. Circuit Judge'
				, 'U.S. President And Vice President'
			]:
				race.election = election.id

				print '  {}, District # {}'.format(election.election_date, race.district)

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

					# set the race attribute
					candidate.race = race.id

					parsed_name = parse_name(candidate.raw_name)['name_dict']

					# set the person attribute
					candidate.person = get_or_create_person(parsed_name)['person']

					for k, v in candidate._data.iteritems():
						print '   {0}: {1}'.format(k, v)

					print '------'

					# now save
					try:
						with db.atomic():
							candidate.save()
					except Exception as e:
						if 'duplicate' in e.message:
							pass
						else:
							print 'Error on line #{0}: {1}'.format(inspect.currentframe().f_lineno, e)

				print '==================='
print 'fin.'

