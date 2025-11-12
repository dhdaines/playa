##  Makefile (for maintenance purpose)
##

PYTHON=python
RM=rm -f
CP=cp -f
MKDIR=mkdir

CONV_CMAP=$(PYTHON) ../../tools/conv_cmap.py
CMAPSRC=resources
CMAPDST=.
cmap: $(CMAPDST)/to-unicode-Adobe-CNS1.pickle.gz $(CMAPDST)/to-unicode-Adobe-GB1.pickle.gz \
	$(CMAPDST)/to-unicode-Adobe-Japan1.pickle.gz $(CMAPDST)/to-unicode-Adobe-Korea1.pickle.gz \
	$(CMAPDST)/to-unicode-Adobe-KR.pickle.gz $(CMAPDST)/to-unicode-Adobe-Manga1.pickle.gz
cmap_clean:
	-$(RM) $(CMAPDST)/*.pickle.gz
$(CMAPDST)/to-unicode-Adobe-CNS1.pickle.gz: $(CMAPSRC)/Adobe-CNS1-7/cid2code.txt
	$(CONV_CMAP) -c B5=cp950 -c UniCNS-UTF8=utf-8 \
		$(CMAPDST) Adobe-CNS1 $(CMAPSRC)/Adobe-CNS1-7/cid2code.txt
$(CMAPDST)/to-unicode-Adobe-GB1.pickle.gz: $(CMAPSRC)/Adobe-GB1-6/cid2code.txt
	$(CONV_CMAP) -c GBK-EUC=cp936 -c UniGB-UTF8=utf-8 \
		$(CMAPDST) Adobe-GB1 $(CMAPSRC)/Adobe-GB1-6/cid2code.txt
$(CMAPDST)/to-unicode-Adobe-Japan1.pickle.gz: $(CMAPSRC)/Adobe-Japan1-7/cid2code.txt
	$(CONV_CMAP) -c RKSJ=cp932 -c EUC=euc-jp -c UniJIS-UTF8=utf-8 \
		$(CMAPDST) Adobe-Japan1 $(CMAPSRC)/Adobe-Japan1-7/cid2code.txt
$(CMAPDST)/to-unicode-Adobe-Korea1.pickle.gz: $(CMAPSRC)/Adobe-Korea1-2/cid2code.txt
	$(CONV_CMAP) -c KSC-EUC=euc-kr -c KSC-Johab=johab -c KSCms-UHC=cp949 -c UniKS-UTF8=utf-8 \
		$(CMAPDST) Adobe-Korea1 $(CMAPSRC)/Adobe-Korea1-2/cid2code.txt
$(CMAPDST)/to-unicode-Adobe-KR.pickle.gz: $(CMAPSRC)/Adobe-KR-9/cid2code.txt
	$(CONV_CMAP) -c UniAKR-UTF8=utf-8 -c UniAKR-UTF16=utf-16be -c UniAKR-UTF32=utf-32be \
		$(CMAPDST) Adobe-KR $(CMAPSRC)/Adobe-KR-9/cid2code.txt
$(CMAPDST)/to-unicode-Adobe-Manga1.pickle.gz: $(CMAPSRC)/Adobe-Manga1-0/cid2code.txt
	$(CONV_CMAP) -c UniManga-UTF8=utf-8 -c UniManga-UTF16=utf-16be -c UniManga-UTF32=utf-32be \
		$(CMAPDST) Adobe-Manga1 $(CMAPSRC)/Adobe-Manga1-0/cid2code.txt
